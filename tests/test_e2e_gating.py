"""The E2E suite must not gate a pull request on the published storefront.

A packaged theme is imported unpublished, so a pull request's Liquid and assets
are never what `E2E_BASE_URL` serves. Running the suite against the live store
and letting it gate the diff produces a check that is wrong in both directions:
green says nothing about the branch, and red says production is broken, which no
edit to the branch can fix.

That is not hypothetical. `e2124f4` gated PR runs behind `E2E_PR_BASE_URL` for
exactly this reason and `0cfaf29` removed the gate ten minutes later, after
which PR #88 sat red for hours because the published store had lost its section
settings. These assertions keep the gate attached to the reason for it.

The suites still run against the live store - the production signal is worth
having - but as a warning rather than a verdict on someone's diff.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "e2e-theme.yml"
)

# Every job that drives a browser against E2E_BASE_URL.
BROWSER_JOBS = ("functional", "accessibility")


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def job_steps(name: str) -> list[dict]:
    return workflow()["jobs"][name]["steps"]


def run_step(name: str) -> dict:
    """The step that actually executes Playwright."""
    steps = [step for step in job_steps(name) if step.get("id") == "e2e"]
    assert len(steps) == 1, f"{name} should run Playwright in exactly one identified step"
    return steps[0]


class TargetDecisionTests(unittest.TestCase):
    def test_validate_publishes_whether_the_run_measures_this_pr(self) -> None:
        outputs = workflow()["jobs"]["validate"].get("outputs", {})
        self.assertIn("tests_this_pr", outputs)

    def test_the_decision_reads_the_pr_base_url_through_the_environment(self) -> None:
        step = [s for s in job_steps("validate") if s.get("id") == "target"][0]
        # A repository variable is settable by anyone with repo access, so it
        # must not be interpolated into a shell script.
        self.assertIn("PR_BASE_URL", step["env"])
        self.assertNotIn("${{ vars.E2E_PR_BASE_URL }}", step["run"])
        self.assertIn("${{ vars.E2E_PR_BASE_URL }}", step["env"]["PR_BASE_URL"])


class BrowserJobGatingTests(unittest.TestCase):
    def test_browser_jobs_can_read_the_decision(self) -> None:
        for name in BROWSER_JOBS:
            with self.subTest(job=name):
                self.assertIn("validate", workflow()["jobs"][name]["needs"])

    def test_a_run_against_the_published_store_cannot_fail_the_pr(self) -> None:
        for name in BROWSER_JOBS:
            with self.subTest(job=name):
                self.assertEqual(
                    "${{ needs.validate.outputs.tests_this_pr != 'true' }}",
                    run_step(name)["continue-on-error"],
                )

    def test_a_run_against_this_pr_still_gates_it(self) -> None:
        # The same expression is what keeps the gate real when a preview URL is
        # configured, so assert the negative directly rather than trusting the
        # string above to mean what it reads like.
        for name in BROWSER_JOBS:
            with self.subTest(job=name):
                self.assertNotIn("continue-on-error: true", WORKFLOW.read_text(encoding="utf-8"))
                self.assertIn("tests_this_pr != 'true'", run_step(name)["continue-on-error"])

    def test_a_failure_against_the_published_store_is_still_reported(self) -> None:
        # Not gating must not mean going quiet: a broken storefront has to stay
        # visible, which is the whole reason the suite runs on every PR.
        for name in BROWSER_JOBS:
            with self.subTest(job=name):
                report = [
                    step for step in job_steps(name)
                    if str(step.get("name", "")).startswith("Report")
                ]
                self.assertEqual(1, len(report))
                self.assertEqual("always()", report[0]["if"])
                self.assertIn("::warning", report[0]["run"])
                self.assertIn("OUTCOME", report[0]["env"])


if __name__ == "__main__":
    unittest.main()
