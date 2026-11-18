import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugin"
    / "skills"
    / "quasar"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

import inbox_watcher  # noqa: E402


class TestInboxWatcherOpenGuard(unittest.TestCase):
    def test_check_pr_not_open_variants(self) -> None:
        self.assertIsNone(inbox_watcher._check_pr_not_open({"state": "open", "merged": False, "draft": False}))
        self.assertIsNone(inbox_watcher._check_pr_not_open({"state": "OPEN"}))
        self.assertEqual(inbox_watcher._check_pr_not_open({"state": "closed", "merged": False}), "closed")
        self.assertEqual(inbox_watcher._check_pr_not_open({"state": "closed", "merged": True}), "merged")
        self.assertEqual(inbox_watcher._check_pr_not_open({"state": "merged"}), "merged")
        self.assertEqual(inbox_watcher._check_pr_not_open({"state": "ABANDONED"}), "abandoned")
        self.assertEqual(
            inbox_watcher._check_pr_not_open({"state": "open", "draft": True}, include_drafts=False),
            "draft",
        )
        self.assertIsNone(
            inbox_watcher._check_pr_not_open({"state": "open", "draft": True}, include_drafts=True)
        )

    def test_run_precompute_skips_closed_github_pr_before_collect_or_agy(self) -> None:
        state = {
            "items": {
                "owner__repo__42": {
                    "id": "owner__repo__42",
                    "provider": "github",
                    "owner": "owner",
                    "repo": "repo",
                    "number": 42,
                    "url": "https://github.com/owner/repo/pull/42",
                    "status": "queued",
                    "openInQueue": True,
                    "manualAutoReviewQueued": True,
                }
            }
        }
        saved_states = []

        with mock.patch.object(inbox_watcher, "load_inbox_state", return_value=state), \
             mock.patch.object(inbox_watcher, "save_inbox_state", side_effect=lambda s: saved_states.append(s)), \
             mock.patch.object(inbox_watcher, "_scan_completed_sessions_for_pr", return_value=[]), \
             mock.patch.object(inbox_watcher, "get_github_token", return_value="tok"), \
             mock.patch.object(
                 inbox_watcher,
                 "_gh_api_get",
                 return_value={"state": "closed", "merged": True, "head": {"sha": "abc123"}},
             ), \
             mock.patch.object(inbox_watcher, "find_agy_binary", side_effect=AssertionError("should not reach agy")), \
             mock.patch.object(inbox_watcher.subprocess, "run", side_effect=AssertionError("should not run collect")):
            res = inbox_watcher.run_precompute_for_item(
                "owner__repo__42",
                settings={"includeDrafts": False},
                count_against_daily_budget=True,
            )

        self.assertTrue(res["ok"])
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "pr_merged")
        self.assertFalse(state["items"]["owner__repo__42"]["openInQueue"])
        self.assertNotIn("manualAutoReviewQueued", state["items"]["owner__repo__42"])
        self.assertEqual(len(saved_states), 1)

    def test_run_precompute_skips_closed_gerrit_cl_after_collect_before_agy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            item_id = "gerrit__host__proj__99"
            state = {
                "items": {
                    item_id: {
                        "id": item_id,
                        "provider": "gerrit",
                        "owner": "gerrit.example.com",
                        "repo": "proj",
                        "number": 99,
                        "url": "https://gerrit.example.com/c/proj/+/99",
                        "status": "queued",
                        "openInQueue": True,
                    }
                }
            }

            def fake_collect(cmd, env=None, capture_output=True, text=True, timeout=90):
                item_dir = Path(tmp) / item_id
                item_dir.mkdir(parents=True, exist_ok=True)
                (item_dir / "pr_context.json").write_text(
                    json.dumps({"pr": {"state": "merged", "number": 99}}),
                    encoding="utf-8",
                )
                proc = mock.Mock()
                proc.returncode = 0
                proc.stdout = json.dumps({"ok": True, "halt_llm_review": False})
                proc.stderr = ""
                return proc

            with mock.patch.object(inbox_watcher, "INBOX_ITEMS_DIR", tmp), \
                 mock.patch.object(inbox_watcher, "load_inbox_state", return_value=state), \
                 mock.patch.object(inbox_watcher, "save_inbox_state"), \
                 mock.patch.object(inbox_watcher, "_scan_completed_sessions_for_pr", return_value=[]), \
                 mock.patch.object(inbox_watcher, "adopt_completed_session_into_inbox", return_value=False), \
                 mock.patch.object(inbox_watcher, "find_agy_binary", return_value="/usr/local/bin/agy"), \
                 mock.patch.object(inbox_watcher.subprocess, "run", side_effect=fake_collect), \
                 mock.patch.object(inbox_watcher.subprocess, "Popen", side_effect=AssertionError("should not invoke agy")):
                res = inbox_watcher.run_precompute_for_item(
                    item_id,
                    settings={"includeDrafts": False, "effort": "high"},
                    count_against_daily_budget=True,
                )

            self.assertTrue(res["ok"])
            self.assertTrue(res["skipped"])
            self.assertEqual(res["reason"], "pr_merged")
            self.assertFalse(state["items"][item_id]["openInQueue"])
            self.assertEqual(state["items"][item_id]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
