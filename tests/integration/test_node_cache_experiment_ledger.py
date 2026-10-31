"""Offline deletion and scope boundaries for §AR-ci.requirements.1.verification."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[2] / "scripts/node_cache_experiment_ledger.py"
SPEC = importlib.util.spec_from_file_location("node_cache_experiment_ledger", PATH)
LEDGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEDGER)


class ExperimentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.config = {"source": "a" * 40, "harness": "b" * 40,
                       "experiment": "grund-1122", "condition": "save", "os": "Windows"}
        self.environment = {"GITHUB_REPOSITORY": LEDGER.REPOSITORY, "GITHUB_REF": LEDGER.REF,
                            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": "b" * 40,
                            "RUNNER_OS": "Windows"}

    def test_each_positive_scope_check_is_required(self):
        for key, wrong in (("GITHUB_REPOSITORY", "agent-grounds/grund"),
                           ("GITHUB_REF", "refs/heads/main"), ("GITHUB_EVENT_NAME", "push"),
                           ("GITHUB_SHA", "c" * 40), ("RUNNER_OS", "Linux")):
            with self.subTest(key=key), mock.patch.dict(os.environ, {**self.environment, key: wrong}):
                with self.assertRaises(ValueError):
                    LEDGER.scope(self.config)
        with mock.patch.dict(os.environ, self.environment):
            LEDGER.scope(self.config)
            with self.assertRaises(ValueError):
                LEDGER.scope({**self.config, "experiment": ""})

    def test_only_full_exact_key_and_ref_can_match(self):
        key = LEDGER.planned(self.config, "100", "1", "Windows")["entries"][0]["key"]
        others = [{"id": 1, "key": key + "-other", "ref": LEDGER.REF},
                  {"id": 2, "key": key, "ref": "refs/heads/main"}]
        with mock.patch.object(LEDGER, "api", return_value={"actions_caches": others}):
            self.assertIsNone(LEDGER.exact_entry(key))
        with mock.patch.object(LEDGER, "api") as api:
            with self.assertRaises(ValueError):
                LEDGER.exact_entry("Windows-node-target-v4-production")
            api.assert_not_called()

    def test_reconcile_rejects_tampered_plan_before_api_calls(self):
        ledger = LEDGER.planned(self.config, "100", "1", "Windows")
        ledger["entries"][0]["key"] += "-unplanned"
        with mock.patch.object(LEDGER, "api") as api:
            with self.assertRaises(ValueError):
                LEDGER.reconcile(ledger, Path("unused"))
            api.assert_not_called()

    def test_cancelled_finalize_is_recovered_and_only_exact_id_deleted(self):
        plan = LEDGER.planned(self.config, "100", "1", "Windows")
        entry = plan["entries"][0]
        remote = {"id": 73, "key": entry["key"], "ref": LEDGER.REF, "size_in_bytes": 4096}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with mock.patch.object(LEDGER, "exact_entry", side_effect=[remote, None, None]):
                LEDGER.reconcile(plan, directory / "recovered.json")
            self.assertEqual(73, entry["id"])
            with mock.patch.object(LEDGER, "exact_entry", side_effect=[remote, None]), \
                    mock.patch.object(LEDGER, "api") as api:
                LEDGER.remove(entry, directory / "deleted.json")
                api.assert_called_once_with("actions/caches/73", "DELETE")
                self.assertIn('"verified_absent": true', (directory / "deleted.json").read_text())

    def test_capacity_never_deletes_unrelated_entries(self):
        entries = [{"key": "ordinary-production", "size_in_bytes": 8 * 1024**3}]
        with mock.patch.object(LEDGER, "caches", return_value=entries), mock.patch.object(LEDGER, "api") as api:
            with self.assertRaises(ValueError):
                LEDGER.capacity(1)
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
