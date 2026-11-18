import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugin"
    / "skills"
    / "quasar"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

import manage_fixes  # noqa: E402


class TestManageFixesInlineDiscussion(unittest.TestCase):
    def test_extract_clean_thread_messages_filters_pending_and_placeholders(self) -> None:
        thread = {
            "messages": [
                {"author": "Quasar", "body": "**Title**\n\n---\n**Draft GitHub Comment**:\n> Fix this."},
                {"author": "You", "body": "Should we use null instead of throwing?"},
                {"author": "Quasar", "body": "⏳ Quasar is analyzing your comment / question...", "pending": True},
                {"author": "Quasar", "body": "⏳ Quasar is thinking..."},
                {"author": "Quasar", "body": "Yes, returning null matches the rest of the module."},
                {"author": "You", "body": "   "},
            ]
        }
        cleaned = manage_fixes.extract_clean_thread_messages(thread)
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned[1]["author"], "You")
        self.assertEqual(cleaned[1]["body"], "Should we use null instead of throwing?")
        self.assertEqual(cleaned[2]["author"], "Quasar")
        self.assertEqual(cleaned[2]["body"], "Yes, returning null matches the rest of the module.")

    def test_ai_candidate_without_followup_has_no_duplicate_discussion(self) -> None:
        thread = {
            "kind": "ai_candidate",
            "draftComment": "Handle empty input.",
            "messages": [
                {
                    "author": "Quasar",
                    "body": "**Handle empty input**\n\n---\n**Draft GitHub Comment**:\n> Handle empty input.",
                }
            ],
        }
        cleaned = manage_fixes.extract_clean_thread_messages(thread)
        followup = manage_fixes.extract_followup_discussion(thread, cleaned)
        self.assertEqual(followup, [])
        self.assertEqual(manage_fixes.format_discussion_block(followup), "")

    def test_ai_candidate_with_inline_chat_extracts_only_followup(self) -> None:
        thread = {
            "kind": "ai_candidate",
            "draftComment": "Handle empty input.",
            "messages": [
                {
                    "author": "Quasar",
                    "body": "**Handle empty input**\n\n---\n**Draft GitHub Comment**:\n> Handle empty input.",
                },
                {"author": "You", "body": "Let's return an empty list instead of throwing."},
                {"author": "Quasar", "body": "Agreed—returning `[]` avoids breaking callers."},
            ],
        }
        cleaned = manage_fixes.extract_clean_thread_messages(thread)
        followup = manage_fixes.extract_followup_discussion(thread, cleaned)
        self.assertEqual(
            followup,
            [
                {"author": "You", "body": "Let's return an empty list instead of throwing."},
                {"author": "Quasar", "body": "Agreed—returning `[]` avoids breaking callers."},
            ],
        )
        block = manage_fixes.format_discussion_block(followup)
        self.assertIn("Inline Thread Discussion", block)
        self.assertIn("**You**: Let's return an empty list instead of throwing.", block)
        self.assertIn("**Quasar**: Agreed—returning `[]` avoids breaking callers.", block)

    def test_github_existing_skips_duplicate_first_message_keeps_replies_and_chat(self) -> None:
        thread = {
            "kind": "github_existing",
            "draftComment": "Please rename this variable.",
            "messages": [
                {"author": "reviewer", "body": "Please rename this variable."},
                {"author": "You", "body": "What name fits best here?"},
                {"author": "Quasar", "body": "`normalizedPath` matches the neighboring helper."},
            ],
        }
        cleaned = manage_fixes.extract_clean_thread_messages(thread)
        followup = manage_fixes.extract_followup_discussion(thread, cleaned)
        self.assertEqual(len(followup), 2)
        self.assertEqual(followup[0]["author"], "You")
        self.assertEqual(followup[1]["author"], "Quasar")

    def test_user_question_without_draft_does_not_duplicate(self) -> None:
        thread = {
            "kind": "user_question",
            "draftComment": "",
            "messages": [
                {"author": "You", "body": "Can we simplify this loop?"},
                {"author": "Quasar", "body": "Yes, a list comprehension is cleaner."},
            ],
        }
        cleaned = manage_fixes.extract_clean_thread_messages(thread)
        followup = manage_fixes.extract_followup_discussion(thread, cleaned)
        self.assertEqual(followup, [])

    def test_prepare_fix_cli_includes_inline_conversation_in_agent_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            repo_dir.mkdir()
            target_file = repo_dir / "example.py"
            target_file.write_text("def foo(x):\n    return x + 1\n", encoding="utf-8")

            state_root = Path(tmp) / "quasar_state"
            state_root.mkdir()
            session = {
                "sessionId": "test-session-1",
                "repoDir": str(repo_dir),
                "workspaceDir": str(repo_dir),
                "headSnapshotRoot": "",
                "pr": {
                    "number": 42,
                    "title": "Test PR",
                    "headRefName": "feat",
                    "baseRefName": "main",
                    "isOwnedByUser": True,
                },
                "threads": [
                    {
                        "id": "finding-1",
                        "kind": "ai_candidate",
                        "severity": "DESIGN",
                        "title": "Validate input before adding",
                        "path": "example.py",
                        "startLine": 1,
                        "endLine": 2,
                        "whyItMatters": "None input causes TypeError.",
                        "draftComment": "Check for None before adding 1.",
                        "selectedForFix": True,
                        "messages": [
                            {
                                "author": "Quasar",
                                "body": "**Validate input before adding**\n\n---\n**Draft GitHub Comment**:\n> Check for None before adding 1.",
                            },
                            {
                                "author": "You",
                                "body": "Instead of raising, let's default None to 0.",
                            },
                            {
                                "author": "Quasar",
                                "body": "Makes sense—defaulting `None` to `0` keeps `foo(None) == 1`.",
                            },
                            {
                                "author": "Quasar",
                                "body": "⏳ Quasar is analyzing your comment / question...",
                                "pending": True,
                            },
                        ],
                    }
                ],
            }

            # Resolve where manage_fixes looks for active_session.json under overridden HOME
            env = dict(os.environ)
            env["HOME"] = tmp
            sys_env_code = (
                f"import sys; sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
                f"from collect_pr_context import get_session_paths; "
                f"print(get_session_paths({str(repo_dir)!r})[1])"
            )
            path_proc = subprocess.run(
                [sys.executable, "-c", sys_env_code],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            active_session_path = Path(path_proc.stdout.strip())
            active_session_path.parent.mkdir(parents=True, exist_ok=True)
            active_session_path.write_text(json.dumps(session), encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "manage_fixes.py"),
                    "--prepare-fix",
                    "--workspace-dir",
                    str(repo_dir),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            out = json.loads(proc.stdout)
            self.assertTrue(out["ok"])
            prompt = out["agentPrompt"]
            self.assertIn("Inline Thread Discussion", prompt)
            self.assertIn("Instead of raising, let's default None to 0.", prompt)
            self.assertIn("defaulting `None` to `0` keeps `foo(None) == 1`", prompt)
            self.assertNotIn("⏳ Quasar is analyzing", prompt)
            self.assertNotIn("**Draft GitHub Comment**:", prompt)

            fix_req = json.loads(Path(out["fixRequestPath"]).read_text(encoding="utf-8"))
            item = fix_req["items"][0]
            self.assertEqual(len(item["followupDiscussion"]), 2)
            self.assertEqual(len(item["threadDiscussion"]), 3)


if __name__ == "__main__":
    unittest.main()
