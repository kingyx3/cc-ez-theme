"""Keep the EasyStore release workflow separate from feature-branch CI.

A short-lived EasyStore admin session expired during a feature-branch run and
failed an otherwise green PR. Only main is permitted to import/publish
automatically, as documented by the deployment and production safety runbooks.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-theme.yml"


class ThemeDeploymentGateTests(unittest.TestCase):
    def test_feature_branches_validate_and_package_without_deploying(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('    branches:\n      - "**"', workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertIn("  test:\n", workflow)
        self.assertIn("  package:\n", workflow)

        deploy = workflow.split("\n  deploy:\n", maxsplit=1)[1]
        gate = (
            "    if: github.ref == 'refs/heads/main' && "
            "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
        )
        self.assertIn(gate, deploy)
        self.assertLess(deploy.index(gate), deploy.index("    name: Import and publish"))
        self.assertIn("    needs: package", deploy)
        self.assertIn("    environment:", deploy)


if __name__ == "__main__":
    unittest.main()
