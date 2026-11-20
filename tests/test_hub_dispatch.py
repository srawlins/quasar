import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "plugin" / "sidecars" / "quasar-web"
sys.path.insert(0, str(SERVER_DIR))

import server  # noqa: E402


class TestHubDiscoveryAndDispatch(unittest.TestCase):
    def test_discover_ls_env_uses_hub_json_and_prefers_exact_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon_dir = Path(tmp) / ".gemini" / "antigravity" / "daemon"
            daemon_dir.mkdir(parents=True)
            live_pid_review = os.getpid()
            # Use parent pid as second live PID
            live_pid_packages = os.getppid() or os.getpid()

            (daemon_dir / "hub_60312.json").write_text(
                json.dumps({"pid": live_pid_review, "httpPort": 60312, "csrfToken": "tok-review"}),
                encoding="utf-8",
            )
            (daemon_dir / "hub_60323.json").write_text(
                json.dumps({"pid": live_pid_packages, "httpPort": 60323, "csrfToken": "tok-packages"}),
                encoding="utf-8",
            )
            (daemon_dir / "hub_99999.json").write_text(
                json.dumps({"pid": 99999999, "httpPort": 99999, "csrfToken": "tok-dead"}),
                encoding="utf-8",
            )

            ps_output = "\n".join(
                [
                    f"{live_pid_review} /Users/test/.gemini/bin/agy --hub --hub-port=60312 --app_data_dir=antigravity --add-dir=/work/packages-review",
                    f"{live_pid_packages} /Users/test/.gemini/bin/agy --hub --hub-port=60323 --app_data_dir=antigravity --add-dir=/work/packages",
                ]
            )

            clean_env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN")
            }
            with mock.patch.dict(os.environ, clean_env, clear=True), \
                 mock.patch.object(os.path, "expanduser", side_effect=lambda p: p.replace("~", tmp)), \
                 mock.patch.object(server.subprocess, "check_output", return_value=ps_output), \
                 mock.patch.object(os, "getpid", return_value=1):
                env = server.discover_ls_env("/work/packages")

            self.assertEqual(env.get("ANTIGRAVITY_LS_ADDRESS"), "localhost:60323")
            self.assertEqual(env.get("ANTIGRAVITY_CSRF_TOKEN"), "tok-packages")

    def test_dispatch_to_agent_tries_agentapi_new_conversation_without_project_id(self) -> None:
        fake_env = {
            "ANTIGRAVITY_LS_ADDRESS": "localhost:60323",
            "ANTIGRAVITY_CSRF_TOKEN": "tok-packages",
        }
        new_cid = "11111111-2222-3333-4444-555555555555"
        fake_proc = mock.Mock()
        fake_proc.returncode = 0
        fake_proc.stdout = json.dumps({"response": {"conversationId": new_cid}})
        fake_proc.stderr = ""

        captured_cmds = []

        def fake_run(cmd, env=None, capture_output=True, text=True, timeout=12):
            captured_cmds.append(cmd)
            return fake_proc

        with mock.patch.object(server, "get_agentapi_cmd", return_value=["/bin/agentapi"]), \
             mock.patch.object(
                 server,
                 "resolve_conversation_context",
                 return_value=("", "", "/work/packages", fake_env),
             ), \
             mock.patch.object(server, "list_all_sessions", return_value=[]), \
             mock.patch.object(server.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(
                 server,
                 "dispatch_via_agy_cli",
                 side_effect=AssertionError("should not fall back to headless agy CLI when agentapi succeeds"),
             ):
            res = server.dispatch_to_agent("Fix selected comments", title="Quasar Fix", workspace_dir="/work/packages")

        self.assertTrue(res["ok"])
        self.assertEqual(res["mode"], "new-conversation")
        self.assertEqual(res["conversationId"], new_cid)
        self.assertEqual(len(captured_cmds), 1)
        self.assertEqual(captured_cmds[0][:3], ["/bin/agentapi", "new-conversation", "--title=Quasar Fix"])

    def test_standalone_web_mode_dispatches_via_agy_cli_not_desktop_ide_hub(self) -> None:
        with mock.patch.object(server, "STANDALONE_WEB_MODE", True), \
             mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(server, "resolve_conversation_context", return_value=("", "", "/work/repo", {})), \
             mock.patch.object(server, "list_all_sessions", return_value=[]), \
             mock.patch.object(
                 server,
                 "dispatch_via_agy_cli",
                 return_value={"ok": True, "mode": "agy-cli", "conversationId": ""},
             ) as cli_mock, \
             mock.patch.object(
                 server.subprocess,
                 "run",
                 side_effect=AssertionError("standalone web mode should not invoke desktop IDE agentapi"),
             ):
            os.environ.pop("QUASAR_PREFER_IDE_HUB", None)
            res = server.dispatch_to_agent("Review PR #1", title="Quasar Code Review", workspace_dir="/work/repo")

        self.assertTrue(res["ok"])
        self.assertEqual(res["mode"], "agy-cli")
        cli_mock.assert_called_once()

    def test_find_agy_binary_skips_ide_launcher_and_selects_jetski_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_agy = Path(tmp) / "agy"
            fake_jetski = Path(tmp) / "jetski"
            fake_agy.write_text("#!/bin/sh\necho 'Antigravity IDE launcher'\n", encoding="utf-8")
            fake_jetski.write_text("#!/bin/sh\necho '--output-format --print --mode'\n", encoding="utf-8")
            fake_agy.chmod(0o755)
            fake_jetski.chmod(0o755)

            def fake_which(name: str):
                if name == "agy":
                    return str(fake_agy)
                if name == "jetski":
                    return str(fake_jetski)
                return None

            server._AGY_CLI_SUPPORT_CACHE.clear()
            with mock.patch.dict(os.environ, {}, clear=False), \
                 mock.patch.object(os.path, "expanduser", side_effect=lambda p: p.replace("~", tmp)), \
                 mock.patch("shutil.which", side_effect=fake_which), \
                 mock.patch.object(os.path, "isfile", side_effect=lambda p: p in (str(fake_agy), str(fake_jetski))):
                os.environ.pop("AGY_BIN", None)
                chosen = server.find_agy_binary()

            self.assertEqual(chosen, str(fake_jetski))

    def test_extension_js_does_not_skip_agentapi_new_conversation_without_project_id(self) -> None:
        ext_text = (REPO_ROOT / "extension" / "extension.js").read_text(encoding="utf-8")
        self.assertNotIn("if (!env.ANTIGRAVITY_PROJECT_ID) {\n        tryDirectHttpFallback(null);", ext_text)
        self.assertIn("runAgentApi(newConvArgs,", ext_text)


if __name__ == "__main__":
    unittest.main()
