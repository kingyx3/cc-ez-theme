#!/usr/bin/env python3
"""Resolve the imported EasyStore theme id with no third-party runtime dependencies.

Publishing is a `PUT` against a single theme id, so the id has to be discovered
before the request is sent. Guessing it, or reusing an id seen once in a browser
session, would publish whichever theme happens to own that id today. This module
only ever returns an id it can tie back to the theme identity this run stamped
into the package, and fails loudly otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterator, Sequence


ID_KEYS = ("id", "theme_id")
NAME_KEYS = ("name", "theme", "theme_name", "title")
VERSION_KEYS = ("version", "theme_version")
DETAIL_KEYS = NAME_KEYS + (
    "role",
    "status",
    "published",
    "is_published",
    "published_at",
    "updated_at",
    "preview_url",
)
# The resolved id is interpolated into a request URL by the workflow, so only
# path-safe identifiers are accepted here.
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
SCALAR_TYPES = (str, int, float, bool)
# EasyStore reports the theme a storefront is serving as role "main"; every
# other theme is "unpublished".
LIVE_ROLE = "main"
DIAGNOSTIC_LIMIT = 10
# Fields that could say which theme a storefront serves. They are shown even
# when null, because summarize_theme drops null values and a missing state is
# itself the answer the tally is there to give. EasyStore's listing reports
# is_enabled / is_edited / is_deleted rather than a role.
STATE_KEYS = (
    "role",
    "status",
    "published",
    "is_published",
    "is_enabled",
    "is_edited",
    "is_deleted",
)
VALUE_LIMIT = 80
SHAPE_LIMIT = 200
ID_LIST_LIMIT = 10


def normalize_id(value: Any) -> str | None:
    """Return ``value`` as a path-safe id string, or ``None`` when unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and SAFE_ID.fullmatch(value.strip()):
        return value.strip()
    return None


def _entry_id(entry: dict) -> str | None:
    for key in ID_KEYS:
        if key in entry:
            identifier = normalize_id(entry[key])
            if identifier is not None:
                return identifier
    return None


def iter_candidates(document: Any) -> Iterator[dict]:
    """Yield every mapping in ``document`` that carries a usable theme id."""
    queue: list[Any] = [document]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            if _entry_id(current) is not None:
                yield current
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)


def _normalized_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()).casefold() or None


def _field_matches(entry: dict, keys: Sequence[str], wanted: str) -> bool:
    return any(_normalized_text(entry.get(key)) == wanted for key in keys)


def _unique_ids(entries: Sequence[dict]) -> list[str]:
    return list(dict.fromkeys(_entry_id(entry) for entry in entries))


def describe_candidates(document: Any, limit: int = DIAGNOSTIC_LIMIT) -> list[str]:
    """Return short `id=... name=...` lines for the themes found in ``document``."""
    lines = []
    for entry in iter_candidates(document):
        name = next(
            (entry[key] for key in NAME_KEYS if isinstance(entry.get(key), str)),
            "<unnamed>",
        )
        lines.append(f"id={_entry_id(entry)} name={name}")
        if len(lines) == limit:
            break
    return lines


def resolve_theme_id(
    import_document: Any,
    listing_document: Any,
    display_name: str | None = None,
    version: str | None = None,
) -> tuple[str, str]:
    """Return ``(theme_id, source)`` for the theme this run imported.

    Raise ``LookupError`` when no candidate can be tied to the run's identity, or
    when several different ids claim it.
    """
    wanted_name = _normalized_text(display_name)
    wanted_version = _normalized_text(version)

    attempts = (
        ("import response name match", import_document, NAME_KEYS, wanted_name),
        ("import response version match", import_document, VERSION_KEYS, wanted_version),
        ("theme listing name match", listing_document, NAME_KEYS, wanted_name),
        ("theme listing version match", listing_document, VERSION_KEYS, wanted_version),
    )

    for source, document, keys, wanted in attempts:
        if wanted is None:
            continue
        matches = [
            entry
            for entry in iter_candidates(document)
            if _field_matches(entry, keys, wanted)
        ]
        identifiers = _unique_ids(matches)
        if len(identifiers) == 1:
            return identifiers[0], source
        if identifiers:
            raise LookupError(
                f"Several EasyStore themes claim the same identity ({source}): "
                + ", ".join(identifiers)
                + "\nPublishing was stopped because the target theme is ambiguous."
            )

    # The import response describes the theme that was just created, so a single
    # candidate there is unambiguous even without an identity field to match on.
    identifiers = _unique_ids(list(iter_candidates(import_document)))
    if len(identifiers) == 1:
        return identifiers[0], "import response sole theme"

    detail = describe_candidates(listing_document) or ["<none>"]
    raise LookupError(
        "Could not determine the EasyStore theme id for this deployment."
        f"\nExpected theme name: {display_name}"
        f"\nExpected theme version: {version}"
        "\nThemes visible in the listing response:\n" + "\n".join(detail)
    )


def summarize_theme(document: Any, theme_id: Any) -> dict[str, Any]:
    """Return the scalar fields EasyStore reports for ``theme_id``."""
    identifier = normalize_id(theme_id)
    summary: dict[str, Any] = {}
    for entry in iter_candidates(document):
        if _entry_id(entry) != identifier:
            continue
        for key in DETAIL_KEYS:
            value = entry.get(key)
            if key not in summary and isinstance(value, SCALAR_TYPES):
                summary[key] = value
    return summary


def _shape(value: Any, depth: int = 0) -> str:
    """Render one JSON value, showing nested values only ``depth`` levels down."""
    if isinstance(value, dict):
        if depth:
            inner = ", ".join(
                f"{key}={_shape(item, depth - 1)}" for key, item in value.items()
            )
        else:
            inner = ", ".join(sorted(str(key) for key in value))
        text = "{" + inner + "}"
    elif isinstance(value, list):
        text = f"[{len(value)} items]"
    else:
        text = repr(value)
        return text if len(text) <= VALUE_LIMIT else text[: VALUE_LIMIT - 3] + "..."
    return text if len(text) <= SHAPE_LIMIT else text[: SHAPE_LIMIT - 3] + "..."


def _tally(document: Any) -> list[str]:
    """Count the values of each state field across every theme in ``document``."""
    entries = list(iter_candidates(document))
    lines = [f"{len(entries)} themes in the listing; values of each state field:"]
    for key in STATE_KEYS:
        counts: dict[str, int] = {}
        for entry in entries:
            if key in entry:
                shown = _shape(entry[key])
                counts[shown] = counts.get(shown, 0) + 1
        if counts:
            lines.append(
                f"  {key}: " + ", ".join(f"{shown} x{n}" for shown, n in sorted(counts.items()))
            )
    enabled = [_entry_id(entry) for entry in entries if entry.get("is_enabled") == 1]
    lines.append(
        f"  ids with is_enabled=1 (first {ID_LIST_LIMIT}): {enabled[:ID_LIST_LIMIT]}"
    )
    return lines


def inspect_document(document: Any, theme_id: Any = None) -> list[str]:
    """Show everything ``document`` reports, for working out what a response means.

    With a ``theme_id`` this lists every field of that theme and then tallies the
    state fields of every theme. Without one it lists the top level of the
    document, one level of nested values deep.
    """
    lines: list[str] = []
    if theme_id is None:
        if isinstance(document, dict):
            lines.extend(f"{key}: {_shape(value, 1)}" for key, value in document.items())
        else:
            lines.append(_shape(document))
        return lines

    identifier = normalize_id(theme_id)
    entry = next(
        (item for item in iter_candidates(document) if _entry_id(item) == identifier),
        None,
    )
    if entry is None:
        lines.append(f"theme {identifier} is not in the listing")
    else:
        lines.append(f"fields of theme {identifier}:")
        lines.extend(f"  {key}: {_shape(value)}" for key, value in entry.items())
    lines.extend(_tally(document))
    return lines


def is_live(summary: dict[str, Any]) -> bool:
    """Whether the fields EasyStore reports say the storefront serves the theme."""
    role = summary.get("role")
    if role is not None:
        return role == LIVE_ROLE
    return summary.get("published") is True


def load_document(path: Path | str | None) -> Any:
    """Return the parsed JSON at ``path``, or ``None`` when it is unusable."""
    if path is None:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _optional_path(value: str) -> Path | None:
    """Return ``value`` as a path, treating an empty argument as absent.

    An unset environment variable expands to an empty argument rather than
    disappearing, and `Path("")` is the current directory, which would otherwise
    turn a missing file into a confusing directory error.
    """
    return Path(value) if value.strip() else None


def _run_resolve(args: argparse.Namespace) -> int:
    try:
        theme_id, source = resolve_theme_id(
            load_document(args.import_response),
            load_document(args.themes_response),
            args.display_name,
            args.version,
        )
    except LookupError as error:
        for line in str(error).splitlines():
            print(f"ERROR: {line}")
        return 1

    print(f"Resolved EasyStore theme id {theme_id} ({source})")
    if args.github_output is not None:
        with open(args.github_output, "a", encoding="utf-8") as output:
            print(f"theme_id={theme_id}", file=output)
            print(f"theme_id_source={source}", file=output)
    return 0


def _run_describe(args: argparse.Namespace) -> int:
    summary = summarize_theme(load_document(args.themes_response), args.theme_id)
    if not summary:
        print(f"No EasyStore theme details available for id {args.theme_id}")
        return 0
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


def _run_inspect(args: argparse.Namespace) -> int:
    document = load_document(args.file)
    if document is None:
        print("No readable JSON document to inspect.")
        return 0
    for line in inspect_document(document, args.theme_id):
        print(line)
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    """Fail unless EasyStore reports the theme as the one the storefront serves.

    A successful publish request only proves EasyStore accepted it, so the
    deploy would stay green while the storefront kept serving the old theme.
    """
    summary = summarize_theme(load_document(args.themes_response), args.theme_id)
    if not summary:
        print(f"ERROR: EasyStore did not report theme {args.theme_id} in its listing.")
        return 1
    for key, value in summary.items():
        print(f"{key}: {value}")
    if not is_live(summary):
        print(f"ERROR: Theme {args.theme_id} is not live on the storefront.")
        return 1
    print(f"Verified: theme {args.theme_id} is live on the storefront.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser(
        "resolve", help="resolve the theme id this run imported"
    )
    resolve_parser.add_argument("--import-response", type=_optional_path)
    resolve_parser.add_argument("--themes-response", type=_optional_path)
    resolve_parser.add_argument("--display-name")
    resolve_parser.add_argument("--version")
    resolve_parser.add_argument("--github-output", type=_optional_path)

    describe_parser = subparsers.add_parser(
        "describe", help="print the fields EasyStore reports for a theme id"
    )
    describe_parser.add_argument("--themes-response", type=_optional_path)
    describe_parser.add_argument("--theme-id", required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="fail unless EasyStore reports the theme as live"
    )
    verify_parser.add_argument("--themes-response", type=_optional_path)
    verify_parser.add_argument("--theme-id", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="print everything a response reports, for diagnosis"
    )
    inspect_parser.add_argument("--file", type=_optional_path)
    inspect_parser.add_argument("--theme-id")

    args = parser.parse_args(argv)
    if args.command == "resolve":
        return _run_resolve(args)
    if args.command == "inspect":
        return _run_inspect(args)
    if args.command == "verify":
        return _run_verify(args)
    return _run_describe(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
