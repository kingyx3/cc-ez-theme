from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from scripts import theme_ci


class ThemeCITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def make_theme(self, name: str = "theme") -> Path:
        theme = self.root / name
        for directory in theme_ci.REQUIRED_DIRECTORIES:
            (theme / directory).mkdir(parents=True, exist_ok=True)

        (theme / "assets" / "app.css").write_text("body {}\n", encoding="utf-8")
        (theme / "editor_assets" / "app.css").write_text(
            "body {}\n", encoding="utf-8"
        )
        (theme / "config" / "settings_data.json").write_text(
            '{"current": {}}\n', encoding="utf-8"
        )
        (theme / "config" / "settings_schema.json").write_text(
            "[]\n", encoding="utf-8"
        )
        (theme / "editor_config" / "settings_data.json").write_text(
            '{"current": {}}\n', encoding="utf-8"
        )
        (theme / "editor_config" / "settings_schema.json").write_text(
            "[]\n", encoding="utf-8"
        )
        (theme / "layout" / "theme.liquid").write_text(
            "{{ content_for_layout }}\n", encoding="utf-8"
        )
        (theme / "sections" / "hero.liquid").write_text(
            '<h1>{{ section.settings.title }}</h1>\n'
            "{% schema %}\n"
            '{"name": "Hero", "settings": []}\n'
            "{% endschema %}\n",
            encoding="utf-8",
        )
        (theme / "sections" / "plain.liquid").write_text(
            "<p>Static section</p>\n", encoding="utf-8"
        )
        (theme / "snippets" / "card.liquid").write_text(
            "<article>Card</article>\n", encoding="utf-8"
        )
        (theme / "templates" / "home.liquid").write_text(
            "{{ 'app.css?v=1' | asset_url }}\n"
            "{% section 'hero' %}\n"
            "{% include 'card' %}\n"
            "{% comment %}{% include 'not-a-real-snippet' %}{% endcomment %}\n",
            encoding="utf-8",
        )
        (theme / "templates" / "ignored.liquid.backup").write_text(
            "Not a runtime template\n", encoding="utf-8"
        )
        (theme / "README.md").write_text("Not shipped\n", encoding="utf-8")
        return theme

    def make_zip(self, name: str, entries: list[tuple[str, str]]) -> Path:
        archive_path = self.root / name
        with zipfile.ZipFile(archive_path, "w") as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for filename, content in entries:
                    archive.writestr(filename, content)
        return archive_path

    def test_valid_theme_and_deterministic_package(self) -> None:
        theme = self.make_theme()
        self.assertEqual(theme_ci.validate_theme(theme), [])

        first_archive = self.root / "first.zip"
        second_archive = self.root / "nested" / "second.zip"
        first_digest = theme_ci.build_archive(theme, first_archive)
        second_digest = theme_ci.build_archive(theme, second_archive)

        self.assertEqual(first_digest, second_digest)
        self.assertEqual(first_digest, theme_ci.sha256_file(first_archive))
        self.assertEqual(theme_ci.validate_archive(first_archive), [])
        with zipfile.ZipFile(first_archive) as archive:
            names = archive.namelist()
        self.assertIn("cc-ez-theme/layout/theme.liquid", names)
        self.assertIn("cc-ez-theme/editor_assets/app.css", names)
        self.assertIn("cc-ez-theme/editor_config/settings_schema.json", names)
        self.assertNotIn("README.md", names)
        self.assertNotIn(
            "cc-ez-theme/templates/ignored.liquid.backup", names
        )

    def test_missing_and_non_directory_theme_paths(self) -> None:
        missing = self.root / "missing"
        self.assertIn("does not exist", theme_ci.validate_theme(missing)[0])

        file_path = self.root / "file"
        file_path.write_text("not a directory", encoding="utf-8")
        self.assertIn("not a directory", theme_ci.validate_theme(file_path)[0])

    def test_required_structure_errors(self) -> None:
        theme = self.make_theme()
        (theme / "assets" / "app.css").unlink()
        (theme / "assets").rmdir()
        (theme / "layout" / "theme.liquid").unlink()

        issues = theme_ci.validate_theme(theme)
        self.assertTrue(any("Missing required directory: assets/" in issue for issue in issues))
        self.assertTrue(
            any("Missing required file: layout/theme.liquid" in issue for issue in issues)
        )

    def test_asset_and_editor_asset_filenames_must_match(self) -> None:
        theme = self.make_theme()
        (theme / "assets" / "storefront-only.js").write_text(
            "window.storefront = true;\n", encoding="utf-8"
        )
        (theme / "editor_assets" / "editor-only.js").write_text(
            "window.editor = true;\n", encoding="utf-8"
        )

        issues = theme_ci.validate_theme(theme)
        self.assertIn(
            "editor_assets/: missing counterpart for assets/storefront-only.js",
            issues,
        )
        self.assertIn(
            "assets/: missing counterpart for editor_assets/editor-only.js",
            issues,
        )

    def test_file_safety_encoding_and_json_errors(self) -> None:
        theme = self.make_theme()
        (theme / ".DS_Store").write_text("metadata", encoding="utf-8")
        (theme / "__MACOSX").mkdir()
        (theme / "__MACOSX" / "junk").write_text("junk", encoding="utf-8")
        (theme / "config" / "broken.json").write_text("{", encoding="utf-8")
        (theme / "snippets" / "binary.liquid").write_bytes(b"\xff")
        (theme / "snippets" / "linked.liquid").symlink_to(
            theme / "layout" / "theme.liquid"
        )

        issues = theme_ci.validate_theme(theme)
        self.assertTrue(any("forbidden metadata path" in issue for issue in issues))
        self.assertTrue(any("invalid JSON" in issue for issue in issues))
        self.assertTrue(any("cannot read as UTF-8" in issue for issue in issues))
        self.assertTrue(any("symbolic links are not allowed" in issue for issue in issues))

    def test_missing_asset_and_section_references(self) -> None:
        theme = self.make_theme()
        (theme / "templates" / "home.liquid").write_text(
            "{{ 'missing.css' | asset_url }}\n"
            "{% section 'missing' %}\n"
            "{% render 'missing' %}\n",
            encoding="utf-8",
        )

        issues = theme_ci.validate_theme(theme)
        self.assertTrue(any("missing local asset 'missing.css'" in issue for issue in issues))
        self.assertTrue(any("missing section 'missing'" in issue for issue in issues))
        self.assertTrue(any("missing snippet 'missing'" in issue for issue in issues))

    def test_section_schema_errors(self) -> None:
        theme = self.make_theme()
        cases = {
            "unpaired.liquid": "{% schema %}{}",
            "wrong-order.liquid": "{% endschema %}{% schema %}",
            "invalid-json.liquid": "{% schema %}{% endschema %}",
            "not-object.liquid": "{% schema %}[]{% endschema %}",
        }
        for filename, content in cases.items():
            (theme / "sections" / filename).write_text(content, encoding="utf-8")

        issues = theme_ci.validate_theme(theme)
        self.assertTrue(any("expected one schema/endschema pair" in issue for issue in issues))
        self.assertTrue(any("schema tag must appear before endschema" in issue for issue in issues))
        self.assertTrue(any("invalid section schema JSON" in issue for issue in issues))
        self.assertTrue(any("section schema must be a JSON object" in issue for issue in issues))

    def test_archive_path_errors_and_invalid_zip(self) -> None:
        missing = self.root / "missing.zip"
        self.assertIn("does not exist", theme_ci.validate_archive(missing)[0])

        directory = self.root / "directory"
        directory.mkdir()
        self.assertIn("not a file", theme_ci.validate_archive(directory)[0])

        invalid = self.root / "invalid.zip"
        invalid.write_text("not a zip", encoding="utf-8")
        self.assertIn("Cannot read ZIP archive", theme_ci.validate_archive(invalid)[0])

        empty = self.make_zip("empty.zip", [])
        self.assertIn("Archive is empty", theme_ci.validate_archive(empty))

    def test_archive_content_errors(self) -> None:
        archive = self.make_zip(
            "unsafe.zip",
            [
                ("/absolute", "x"),
                ("../escape", "x"),
                ("windows\\path", "x"),
                ("theme/layout/theme.liquid", "x"),
                (".DS_Store", "x"),
                ("__MACOSX/junk", "x"),
                ("duplicate", "one"),
                ("duplicate", "two"),
            ],
        )

        issues = theme_ci.validate_archive(archive)
        self.assertIn("Archive contains duplicate paths", issues)
        self.assertTrue(any("Unsafe archive path" in issue for issue in issues))
        self.assertTrue(
            any("Unexpected archive root" in issue for issue in issues)
        )
        self.assertTrue(any("Forbidden metadata in archive" in issue for issue in issues))
        self.assertTrue(any("Archive is missing directory" in issue for issue in issues))
        self.assertTrue(any("Archive is missing file" in issue for issue in issues))

    def test_archive_crc_failure(self) -> None:
        theme = self.make_theme()
        archive = self.root / "theme.zip"
        theme_ci.build_archive(theme, archive)

        with mock.patch.object(
            zipfile.ZipFile,
            "testzip",
            return_value="cc-ez-theme/assets/app.css",
        ):
            issues = theme_ci.validate_archive(archive)
        self.assertIn(
            "Archive CRC failed for: cc-ez-theme/assets/app.css", issues
        )

    def test_archive_asset_and_editor_asset_filenames_must_match(self) -> None:
        theme = self.make_theme()
        archive = self.root / "theme.zip"
        theme_ci.build_archive(theme, archive)

        entries: list[tuple[str, str]] = []
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                if info.is_dir() or info.filename in {
                    "cc-ez-theme/assets/app.css",
                    "cc-ez-theme/editor_assets/app.css",
                }:
                    continue
                entries.append((info.filename, source.read(info).decode("utf-8")))
        entries.extend(
            [
                ("cc-ez-theme/assets/storefront-only.css", "body {}\n"),
                ("cc-ez-theme/editor_assets/editor-only.css", "body {}\n"),
            ]
        )
        mismatch = self.make_zip("mismatch.zip", entries)

        issues = theme_ci.validate_archive(mismatch)
        self.assertIn(
            "Archive editor_assets/ is missing counterpart for "
            "assets/storefront-only.css",
            issues,
        )
        self.assertIn(
            "Archive assets/ is missing counterpart for "
            "editor_assets/editor-only.css",
            issues,
        )

    def test_build_failure_paths(self) -> None:
        with self.assertRaises(ValueError):
            theme_ci.build_archive(self.root / "missing", self.root / "missing.zip")

        theme = self.make_theme()
        with mock.patch.object(
            theme_ci, "validate_archive", return_value=["synthetic archive failure"]
        ):
            with self.assertRaises(RuntimeError):
                theme_ci.build_archive(theme, self.root / "bad.zip")

    def test_command_line_success_and_failure(self) -> None:
        theme = self.make_theme()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(theme_ci.main(["check", str(theme)]), 0)
            archive = self.root / "cli" / "theme.zip"
            self.assertEqual(
                theme_ci.main(["package", str(theme), str(archive)]),
                0,
            )
            self.assertEqual(
                theme_ci.main(["check", str(self.root / "missing")]),
                1,
            )
            self.assertEqual(
                theme_ci.main(
                    [
                        "package",
                        str(self.root / "missing"),
                        str(self.root / "never.zip"),
                    ]
                ),
                1,
            )

        rendered = output.getvalue()
        self.assertIn("Theme validation passed", rendered)
        self.assertIn("Theme package created", rendered)
        self.assertIn("ERROR:", rendered)


if __name__ == "__main__":
    unittest.main()
