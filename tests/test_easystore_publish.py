from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import easystore_publish


DISPLAY_NAME = "CC main r451 abc1234"
VERSION = "2.0.0+gh.451.abc1234"


class NormalizeIdTests(unittest.TestCase):
    def test_accepts_integers_and_safe_strings(self) -> None:
        self.assertEqual(easystore_publish.normalize_id(1870671), "1870671")
        self.assertEqual(easystore_publish.normalize_id(" 1870671 "), "1870671")
        self.assertEqual(easystore_publish.normalize_id("theme-a_1"), "theme-a_1")

    def test_rejects_unusable_values(self) -> None:
        # A boolean is an int subclass, so `True` would otherwise become "True".
        self.assertIsNone(easystore_publish.normalize_id(True))
        self.assertIsNone(easystore_publish.normalize_id(None))
        self.assertIsNone(easystore_publish.normalize_id(1.5))
        self.assertIsNone(easystore_publish.normalize_id(""))
        self.assertIsNone(easystore_publish.normalize_id("1870671/../9"))
        self.assertIsNone(easystore_publish.normalize_id("a b"))


class IterCandidatesTests(unittest.TestCase):
    def test_walks_nested_documents(self) -> None:
        document = {
            "meta": {"page": 1},
            "themes": [
                {"id": 11, "name": "live"},
                {"theme_id": "12", "name": "candidate"},
                {"name": "no id"},
            ],
        }
        self.assertEqual(
            [entry["name"] for entry in easystore_publish.iter_candidates(document)],
            ["live", "candidate"],
        )

    def test_ignores_scalars_and_unusable_ids(self) -> None:
        self.assertEqual(list(easystore_publish.iter_candidates(None)), [])
        self.assertEqual(list(easystore_publish.iter_candidates("themes")), [])
        self.assertEqual(list(easystore_publish.iter_candidates({"id": None})), [])
        self.assertEqual(
            list(easystore_publish.iter_candidates({"id": {}, "theme_id": 7})),
            [{"id": {}, "theme_id": 7}],
        )


class ResolveThemeIdTests(unittest.TestCase):
    def test_prefers_a_name_match_in_the_import_response(self) -> None:
        theme_id, source = easystore_publish.resolve_theme_id(
            {"theme": {"id": 1870671, "name": DISPLAY_NAME}},
            {"themes": [{"id": 42, "name": "Other"}]},
            DISPLAY_NAME,
            VERSION,
        )
        self.assertEqual(theme_id, "1870671")
        self.assertEqual(source, "import response name match")

    def test_name_match_ignores_case_and_spacing(self) -> None:
        theme_id, _ = easystore_publish.resolve_theme_id(
            {"theme": {"id": 1870671, "theme_name": "  cc  MAIN r451 abc1234 "}},
            None,
            DISPLAY_NAME,
            VERSION,
        )
        self.assertEqual(theme_id, "1870671")

    def test_falls_back_to_a_version_match_in_the_import_response(self) -> None:
        theme_id, source = easystore_publish.resolve_theme_id(
            {"data": [{"id": 55, "name": "renamed", "theme_version": VERSION}]},
            None,
            DISPLAY_NAME,
            VERSION,
        )
        self.assertEqual(theme_id, "55")
        self.assertEqual(source, "import response version match")

    def test_falls_back_to_the_theme_listing(self) -> None:
        listing = {
            "themes": [
                {"id": 1, "name": "Live theme", "role": "main"},
                {"id": 1870671, "name": DISPLAY_NAME, "role": "unpublished"},
            ]
        }
        theme_id, source = easystore_publish.resolve_theme_id(
            {"message": "ok"}, listing, DISPLAY_NAME, VERSION
        )
        self.assertEqual(theme_id, "1870671")
        self.assertEqual(source, "theme listing name match")

    def test_falls_back_to_a_version_match_in_the_theme_listing(self) -> None:
        listing = {
            "themes": [
                {"id": 1, "name": "Live theme"},
                {"id": 1870671, "name": "renamed", "version": VERSION},
            ]
        }
        theme_id, source = easystore_publish.resolve_theme_id(
            None, listing, DISPLAY_NAME, VERSION
        )
        self.assertEqual(theme_id, "1870671")
        self.assertEqual(source, "theme listing version match")

    def test_uses_the_sole_candidate_in_the_import_response(self) -> None:
        theme_id, source = easystore_publish.resolve_theme_id(
            {"id": 1870671}, {"themes": [{"id": 1}, {"id": 2}]}, DISPLAY_NAME, VERSION
        )
        self.assertEqual(theme_id, "1870671")
        self.assertEqual(source, "import response sole theme")

    def test_skips_identity_fields_that_were_not_supplied(self) -> None:
        theme_id, source = easystore_publish.resolve_theme_id(
            {"theme": {"id": 1870671}}, None, None, None
        )
        self.assertEqual(theme_id, "1870671")
        self.assertEqual(source, "import response sole theme")

    def test_rejects_an_ambiguous_identity(self) -> None:
        listing = {
            "themes": [
                {"id": 1870671, "name": DISPLAY_NAME},
                {"id": 1870672, "name": DISPLAY_NAME},
            ]
        }
        with self.assertRaises(LookupError) as raised:
            easystore_publish.resolve_theme_id(None, listing, DISPLAY_NAME, VERSION)

        message = str(raised.exception)
        self.assertIn("1870671", message)
        self.assertIn("1870672", message)
        self.assertIn("ambiguous", message)

    def test_reports_the_visible_themes_when_nothing_matches(self) -> None:
        listing = {"themes": [{"id": 1, "name": "Live theme"}, {"id": 2}]}
        with self.assertRaises(LookupError) as raised:
            easystore_publish.resolve_theme_id(
                {"errors": ["nope"]}, listing, DISPLAY_NAME, VERSION
            )

        message = str(raised.exception)
        self.assertIn(DISPLAY_NAME, message)
        self.assertIn("id=1 name=Live theme", message)
        self.assertIn("id=2 name=<unnamed>", message)

    def test_reports_no_themes_when_the_listing_is_empty(self) -> None:
        with self.assertRaises(LookupError) as raised:
            easystore_publish.resolve_theme_id(None, None, DISPLAY_NAME, VERSION)

        self.assertIn("<none>", str(raised.exception))

    def test_caps_the_diagnostic_theme_list(self) -> None:
        listing = {"themes": [{"id": index} for index in range(1, 25)]}
        self.assertEqual(len(easystore_publish.describe_candidates(listing)), 10)
        self.assertEqual(
            easystore_publish.describe_candidates(listing, limit=2),
            ["id=1 name=<unnamed>", "id=2 name=<unnamed>"],
        )


class SummarizeThemeTests(unittest.TestCase):
    def test_collects_scalar_fields_for_the_theme(self) -> None:
        listing = {
            "themes": [
                {"id": 1, "name": "Live theme", "role": "main"},
                {
                    "id": 1870671,
                    "name": DISPLAY_NAME,
                    "role": "main",
                    "published": True,
                    "published_at": "2026-08-16T04:19:24Z",
                    "preview_url": None,
                    "settings": {"nested": "ignored"},
                },
            ]
        }
        self.assertEqual(
            easystore_publish.summarize_theme(listing, 1870671),
            {
                "name": DISPLAY_NAME,
                "role": "main",
                "published": True,
                "published_at": "2026-08-16T04:19:24Z",
            },
        )

    def test_returns_nothing_for_an_unknown_theme(self) -> None:
        self.assertEqual(easystore_publish.summarize_theme({"id": 1}, 2), {})
        self.assertEqual(easystore_publish.summarize_theme(None, "bad/id"), {})


class LoadDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_reads_json(self) -> None:
        path = self.root / "themes.json"
        path.write_text(json.dumps({"id": 7}), encoding="utf-8")
        self.assertEqual(easystore_publish.load_document(path), {"id": 7})

    def test_tolerates_missing_and_unreadable_files(self) -> None:
        self.assertIsNone(easystore_publish.load_document(None))
        self.assertIsNone(easystore_publish.load_document(self.root / "missing.json"))
        self.assertIsNone(easystore_publish.load_document(self.root))

        broken = self.root / "broken.json"
        broken.write_text("<html>gateway timeout</html>", encoding="utf-8")
        self.assertIsNone(easystore_publish.load_document(broken))

        binary = self.root / "binary.json"
        binary.write_bytes(b"\xff\xfe\x00")
        self.assertIsNone(easystore_publish.load_document(binary))


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write(self, name: str, document: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_resolve_writes_the_step_output(self) -> None:
        import_response = self.write(
            "import.json", {"theme": {"id": 1870671, "name": DISPLAY_NAME}}
        )
        github_output = self.root / "github_output.txt"

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = easystore_publish.main(
                [
                    "resolve",
                    "--import-response",
                    str(import_response),
                    "--themes-response",
                    str(self.root / "missing.json"),
                    "--display-name",
                    DISPLAY_NAME,
                    "--version",
                    VERSION,
                    "--github-output",
                    str(github_output),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Resolved EasyStore theme id 1870671", stdout.getvalue())
        self.assertEqual(
            github_output.read_text(encoding="utf-8"),
            "theme_id=1870671\ntheme_id_source=import response name match\n",
        )

    def test_resolve_without_a_step_output_file(self) -> None:
        import_response = self.write("import.json", {"id": 1870671})

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = easystore_publish.main(
                ["resolve", "--import-response", str(import_response)]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("1870671", stdout.getvalue())

    def test_resolve_fails_when_the_theme_cannot_be_identified(self) -> None:
        themes_response = self.write("themes.json", {"themes": [{"id": 1}, {"id": 2}]})

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = easystore_publish.main(
                [
                    "resolve",
                    "--themes-response",
                    str(themes_response),
                    "--display-name",
                    DISPLAY_NAME,
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("ERROR: Could not determine", stdout.getvalue())

    def test_describe_prints_theme_fields(self) -> None:
        themes_response = self.write(
            "themes.json",
            {"themes": [{"id": 1870671, "name": DISPLAY_NAME, "role": "main"}]},
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = easystore_publish.main(
                [
                    "describe",
                    "--themes-response",
                    str(themes_response),
                    "--theme-id",
                    "1870671",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(f"name: {DISPLAY_NAME}", stdout.getvalue())
        self.assertIn("role: main", stdout.getvalue())

    def test_empty_path_arguments_are_treated_as_absent(self) -> None:
        # An unset environment variable expands to an empty argument, and
        # `Path("")` is the current directory rather than a missing file.
        self.assertEqual(easystore_publish._optional_path(" "), None)
        self.assertEqual(easystore_publish._optional_path("a.json"), Path("a.json"))

        import_response = self.write("import.json", {"id": 1870671})
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = easystore_publish.main(
                [
                    "resolve",
                    "--import-response",
                    str(import_response),
                    "--themes-response",
                    "",
                    "--github-output",
                    "",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("1870671", stdout.getvalue())

    def test_describe_is_never_fatal(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = easystore_publish.main(["describe", "--theme-id", "1870671"])

        self.assertEqual(exit_code, 0)
        self.assertIn("No EasyStore theme details available", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
