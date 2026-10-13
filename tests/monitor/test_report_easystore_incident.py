"""Offline tests for issue-based GitHub Actions incident notifications."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "report_easystore_incident",
    Path(__file__).resolve().parents[2] / ".github/scripts/report_easystore_incident.py",
)
incident = importlib.util.module_from_spec(spec)
spec.loader.exec_module(incident)


class AlertTest(unittest.TestCase):
    def setUp(self):
        self.kwargs = ("mcp-health", "failure", "kingyx3/cc-ez-theme",
                       "kingyx3", "https://github.com/kingyx3/cc-ez-theme/actions/runs/123")

    def test_new_failure_creates_one_assigned_incident(self):
        with patch.object(incident, "gh", side_effect=[json.dumps([]), "https://github.com/example"]) as gh:
            incident.reconcile(*self.kwargs)
        self.assertEqual(gh.call_count, 2)
        self.assertEqual(gh.call_args.args[:3], ("issue", "create", "--repo"))
        self.assertIn("--assignee", gh.call_args.args)
        self.assertIn("kingyx3", gh.call_args.args)

    def test_repeated_failure_comments_instead_of_duplicate(self):
        existing = [{"number": 42, "title": "[EasyStore] production MCP health check failed"}]
        with patch.object(incident, "gh", side_effect=[json.dumps(existing), ""]) as gh:
            incident.reconcile(*self.kwargs)
        self.assertEqual(gh.call_args.args[:3], ("issue", "comment", "42"))

    def test_recovery_closes_open_incident(self):
        existing = [{"number": 42, "title": "[EasyStore] production MCP health check failed"}]
        with patch.object(incident, "gh", side_effect=[json.dumps(existing), "", ""]) as gh:
            incident.reconcile("mcp-health", "success", *self.kwargs[2:])
        self.assertEqual(gh.call_args.args[:3], ("issue", "close", "42"))

    def test_healthy_without_incident_is_noop(self):
        with patch.object(incident, "gh", return_value="[]") as gh:
            incident.reconcile("admin-renewal", "success", *self.kwargs[2:])
        gh.assert_called_once()

    def test_rejects_unknown_sources_and_statuses(self):
        with patch.object(incident, "gh") as gh:
            with self.assertRaises(ValueError):
                incident.reconcile("unknown", "failure", *self.kwargs[2:])
            with self.assertRaises(ValueError):
                incident.reconcile("mcp-health", "cancelled", *self.kwargs[2:])
            gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
