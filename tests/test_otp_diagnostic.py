from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
RUNTIME = THEME / "assets" / "account-otp-diagnostic.js"
EDITOR = THEME / "editor_assets" / "account-otp-diagnostic.js"
CURRENCIES = THEME / "snippets" / "currencies.liquid"


def code_only(source: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


class OtpDiagnosticSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = code_only(RUNTIME.read_text(encoding="utf-8"))

    def test_runtime_and_editor_assets_are_identical(self) -> None:
        self.assertEqual(RUNTIME.read_bytes(), EDITOR.read_bytes())

    def test_probe_is_loaded_but_requires_explicit_opt_in(self) -> None:
        delivery = CURRENCIES.read_text(encoding="utf-8")
        self.assertIn("account-otp-diagnostic.js", delivery)
        self.assertIn("cc_otp_probe", self.source)
        self.assertIn("if (!enabled) return;", self.source)
        self.assertIn("sessionStorage", self.source)

    def test_probe_observes_beforeinput_and_input_without_intercepting_them(self) -> None:
        self.assertIn("addEventListener('beforeinput', describe, true)", self.source)
        self.assertIn("addEventListener('input', describe, true)", self.source)
        for forbidden in (
            "preventDefault(",
            "stopPropagation(",
            "stopImmediatePropagation(",
            "dispatchEvent(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_probe_never_writes_otp_values_or_drives_the_widget(self) -> None:
        self.assertIsNone(re.search(r"\.value\s*=", self.source))
        for forbidden in (
            "fetch(",
            "XMLHttpRequest",
            ".submit(",
            ".requestSubmit(",
            ".click(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_probe_exposes_only_lengths_not_otp_digits(self) -> None:
        self.assertIn("event.data.length", self.source)
        self.assertIn("String(cell.value || '').length", self.source)
        self.assertIn("String(match.target.value || '').length", self.source)
        self.assertNotIn("textContent = event.data", self.source)
        self.assertNotIn("rows.push(event.data", self.source)
        self.assertNotIn("sessionStorage.setItem(STORAGE_KEY, event", self.source)

    def test_probe_reports_the_three_android_outcomes_we_need(self) -> None:
        self.assertIn("PREREQUISITE MET", self.source)
        self.assertIn("NOT SAFE: the preceding beforeinput was not cancelable", self.source)
        self.assertIn("NOT SAFE: six-digit first-cell input had no observed beforeinput", self.source)
        self.assertIn("NATIVE DISTRIBUTION", self.source)


if __name__ == "__main__":
    unittest.main()
