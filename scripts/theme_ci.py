#!/usr/bin/env python3
"""Validate and package the EasyStore theme with no third-party runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Sequence


REQUIRED_DIRECTORIES = (
    "assets",
    "config",
    "layout",
    "sections",
    "snippets",
    "templates",
)
REQUIRED_FILES = (
    "layout/theme.liquid",
    "templates/home.liquid",
)
FORBIDDEN_PARTS = {".git", "__MACOSX"}
SCHEMA_START = re.compile(r"{%\s*schema\s*%}")
SCHEMA_END = re.compile(r"{%\s*endschema\s*%}")
SCHEMA_BLOCK = re.compile(
    r"{%\s*schema\s*%}(?P<body>.*?){%\s*endschema\s*%}",
    re.DOTALL,
)
ASSET_REFERENCE = re.compile(
    r"(?P<quote>['\"])(?P<name>.+?)(?P=quote)\s*\|\s*asset_url\b"
)
SECTION_REFERENCE = re.compile(
    r"{%\s*section\s+(?P<quote>['\"])(?P<name>.+?)(?P=quote)\s*%}"
)
PACKAGE_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def _is_forbidden(path: PurePosixPath) -> bool:
    return path.name == ".DS_Store" or any(
        part in FORBIDDEN_PARTS for part in path.parts
    )


def _validate_liquid(
    path: Path, text: str, theme_dir: Path, issues: list[str]
) -> None:
    relative = path.relative_to(theme_dir).as_posix()

    for match in ASSET_REFERENCE.finditer(text):
        asset_name = match.group("name").partition("?")[0]
        if not (theme_dir / "assets" / asset_name).is_file():
            issues.append(f"{relative}: missing local asset {asset_name!r}")

    for match in SECTION_REFERENCE.finditer(text):
        section_name = match.group("name")
        if not (theme_dir / "sections" / f"{section_name}.liquid").is_file():
            issues.append(f"{relative}: missing section {section_name!r}")

    if path.parent != theme_dir / "sections":
        return

    start_count = len(SCHEMA_START.findall(text))
    end_count = len(SCHEMA_END.findall(text))
    if start_count == 0 and end_count == 0:
        return
    if start_count != 1 or end_count != 1:
        issues.append(
            f"{relative}: expected one schema/endschema pair, "
            f"found {start_count}/{end_count}"
        )
        return

    match = SCHEMA_BLOCK.search(text)
    if match is None:
        issues.append(f"{relative}: schema tag must appear before endschema")
        return

    try:
        schema = json.loads(match.group("body"))
    except json.JSONDecodeError as error:
        issues.append(
            f"{relative}: invalid section schema JSON at "
            f"line {error.lineno}, column {error.colno}"
        )
        return

    if not isinstance(schema, dict):
        issues.append(f"{relative}: section schema must be a JSON object")


def validate_theme(theme_dir: Path | str) -> list[str]:
    """Return all structural and static validation errors for a theme directory."""
    theme_dir = Path(theme_dir)
    if not theme_dir.exists():
        return [f"Theme directory does not exist: {theme_dir}"]
    if not theme_dir.is_dir():
        return [f"Theme path is not a directory: {theme_dir}"]

    issues: list[str] = []

    for directory in REQUIRED_DIRECTORIES:
        if not (theme_dir / directory).is_dir():
            issues.append(f"Missing required directory: {directory}/")

    for filename in REQUIRED_FILES:
        if not (theme_dir / filename).is_file():
            issues.append(f"Missing required file: {filename}")

    for path in sorted(theme_dir.rglob("*")):
        relative_path = path.relative_to(theme_dir)
        relative = relative_path.as_posix()

        if path.is_symlink():
            issues.append(f"{relative}: symbolic links are not allowed")
            continue

        if _is_forbidden(PurePosixPath(relative)):
            issues.append(f"{relative}: forbidden metadata path")

        if not path.is_file() or path.suffix not in {".json", ".liquid"}:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            issues.append(f"{relative}: cannot read as UTF-8 ({error})")
            continue

        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                issues.append(
                    f"{relative}: invalid JSON at "
                    f"line {error.lineno}, column {error.colno}"
                )
        else:
            _validate_liquid(path, text, theme_dir, issues)

    return issues


def validate_archive(archive_path: Path | str) -> list[str]:
    """Return all safety and integrity errors for an EasyStore ZIP archive."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        return [f"Archive does not exist: {archive_path}"]
    if not archive_path.is_file():
        return [f"Archive path is not a file: {archive_path}"]

    issues: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]

            if not infos:
                issues.append("Archive is empty")
            if len(names) != len(set(names)):
                issues.append("Archive contains duplicate paths")

            for name in names:
                path = PurePosixPath(name)
                if name.startswith("/") or "\\" in name or ".." in path.parts:
                    issues.append(f"Unsafe archive path: {name}")
                if path.parts and path.parts[0] == "theme":
                    issues.append(f"Unexpected theme/ wrapper: {name}")
                if _is_forbidden(path):
                    issues.append(f"Forbidden metadata in archive: {name}")

            for directory in REQUIRED_DIRECTORIES:
                prefix = f"{directory}/"
                if not any(name.startswith(prefix) for name in names):
                    issues.append(f"Archive is missing directory: {directory}/")

            for filename in REQUIRED_FILES:
                if filename not in names:
                    issues.append(f"Archive is missing file: {filename}")

            corrupt_file = archive.testzip()
            if corrupt_file is not None:
                issues.append(f"Archive CRC failed for: {corrupt_file}")
    except (OSError, zipfile.BadZipFile) as error:
        issues.append(f"Cannot read ZIP archive: {error}")

    return issues


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_archive(theme_dir: Path | str, output_path: Path | str) -> str:
    """Validate the theme, create a deterministic ZIP, and return its SHA-256."""
    theme_dir = Path(theme_dir)
    output_path = Path(output_path)
    issues = validate_theme(theme_dir)
    if issues:
        raise ValueError("\n".join(issues))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for directory in REQUIRED_DIRECTORIES:
            info = zipfile.ZipInfo(f"{directory}/", PACKAGE_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o40755 << 16
            archive.writestr(info, b"")

        for path in sorted(theme_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(theme_dir)
            if relative.as_posix() == "README.md":
                continue

            info = zipfile.ZipInfo(relative.as_posix(), PACKAGE_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())

    archive_issues = validate_archive(output_path)
    if archive_issues:
        raise RuntimeError("\n".join(archive_issues))

    return sha256_file(output_path)


def _print_issues(issues: Sequence[str]) -> None:
    for issue in issues:
        print(f"ERROR: {issue}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="validate a theme directory")
    check_parser.add_argument("theme_dir", type=Path)

    package_parser = subparsers.add_parser(
        "package", help="validate and create an upload ZIP"
    )
    package_parser.add_argument("theme_dir", type=Path)
    package_parser.add_argument("output_path", type=Path)

    args = parser.parse_args(argv)
    if args.command == "check":
        issues = validate_theme(args.theme_dir)
        if issues:
            _print_issues(issues)
            return 1
        print(f"Theme validation passed: {args.theme_dir}")
        return 0

    try:
        digest = build_archive(args.theme_dir, args.output_path)
    except (ValueError, RuntimeError) as error:
        _print_issues(str(error).splitlines())
        return 1

    print(f"Theme package created: {args.output_path}")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
