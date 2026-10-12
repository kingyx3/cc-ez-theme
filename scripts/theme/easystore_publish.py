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
DIAGNOSTIC_LIMIT = 10


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

    args = parser.parse_args(argv)
    if args.command == "resolve":
        return _run_resolve(args)
    return _run_describe(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
