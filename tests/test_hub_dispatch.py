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

    def test_headless_cli_allow_rules_cover_readonly_probes_and_quasar_scripts(self) -> None:
        captured_cmd = []

        class FakeProc:
            pid = 12345
            stdout = iter(
                [
                    json.dumps({"event": "init", "conversation_id": "22222222-3333-4444-5555-666666666666"}) + "\n",
                    json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "OK"}}) + "\n",
                ]
            )

            def wait(self) -> int:
                return 0

        def fake_popen(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return FakeProc()

        with tempfile.TemporaryDirectory() as ws_dir, \
             mock.patch.object(server, "find_agy_binary", return_value="/usr/local/bin/agy"), \
             mock.patch.object(server.subprocess, "Popen", side_effect=fake_popen):
            res = server.dispatch_via_agy_cli(
                prompt="Review PR #1",
                title="Quasar Code Review",
                workspace_dir=ws_dir,
                effort="low",
                allow_edits=False,
            )
            self.assertTrue(res["ok"])
            # Wait briefly for background stream thread to finish
            import time
            for _ in range(50):
                if not server.ACTIVE_AGENT_JOB.get("active"):
                    break
                time.sleep(0.02)

        settings_arg = next((a for a in captured_cmd if a.startswith("--settings=")), "")
        self.assertTrue(settings_arg, "Expected --settings=... argument")
        allow_rules = json.loads(settings_arg.split("=", 1)[1])["permissions"]["allow"]

        for required_cmd in (
            "command(git)",
            "command(ls)",
            "command(cat)",
            "command(test)",
            "command([)",
            "command(echo)",
            "command(true)",
            "command(rg)",
            "command(find)",
        ):
            self.assertIn(required_cmd, allow_rules)

        # Least-privilege guarantee: read-only review must NOT grant write_file on workspace
        real_ws = os.path.realpath(ws_dir)
        self.assertIn(f"read_file({real_ws}/)", allow_rules)
        self.assertNotIn(f"write_file({real_ws}/)", allow_rules)

        # Verify script regex matches both direct and env-prefixed Quasar script invocations
        import re
        script_rules = [r for r in allow_rules if r.startswith("command(regex:") and r.endswith(")")]
        self.assertTrue(script_rules)
        rx = re.compile(script_rules[0][len("command(regex:") : -1])
        self.assertIsNotNone(rx.search("python3 ~/.gemini/config/plugins/quasar/skills/quasar/scripts/collect_pr_context.py --pr 1"))
        self.assertIsNotNone(rx.search("QUASAR_SESSION_DIR=/tmp/s python3 /x/skills/quasar/scripts/publish_review_session.py --input a.json"))

    def test_headless_cli_surfaces_denied_actions_even_on_success_rc_zero(self) -> None:
        class FakeDeniedProc:
            pid = 23456
            stdout = iter(
                [
                    json.dumps({"event": "init", "conversation_id": "33333333-4444-5555-6666-777777777777"}) + "\n",
                    "cli: no output produced — a tool required the \"command\" permission that headless mode cannot prompt for, so it was auto-denied.\n",
                    json.dumps(
                        {
                            "event": "result",
                            "result": {
                                "status": "SUCCESS",
                                "response": "",
                                "denied_actions": [{"action": "command", "display_name": "RunCommand"}],
                            },
                        }
                    )
                    + "\n",
                ]
            )

            def wait(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as ws_dir, \
             mock.patch.object(server, "find_agy_binary", return_value="/usr/local/bin/agy"), \
             mock.patch.object(server.subprocess, "Popen", return_value=FakeDeniedProc()):
            server.dispatch_via_agy_cli(
                prompt="Review PR #1",
                title="Quasar Code Review",
                workspace_dir=ws_dir,
                effort="low",
                allow_edits=False,
            )
            import time
            for _ in range(50):
                if not server.ACTIVE_AGENT_JOB.get("active"):
                    break
                time.sleep(0.02)

        self.assertTrue(server.ACTIVE_AGENT_JOB.get("cliError"))
        self.assertIn("RunCommand", server.ACTIVE_AGENT_JOB["cliError"])
        status = server.get_live_agent_status(None, [])
        self.assertIn("error", status)
        self.assertIn("RunCommand", status["error"])
        self.assertNotIn("Agent finished", status.get("stage", ""))

    @unittest.skipUnless(
        os.environ.get("QUASAR_LIVE_CLI_TEST") == "1",
        "Set QUASAR_LIVE_CLI_TEST=1 to run live strict-permission headless CLI smoke test",
    )
    def test_live_headless_cli_strict_permissions_readonly_probe(self) -> None:
        cli_bin = server.find_agy_binary()
        self.assertIsNotNone(cli_bin, "No headless CLI binary found")
        real_state_dir = os.path.realpath(os.path.expanduser("~/.gemini/quasar"))
        settings = json.dumps(
            {
                "permissions": {
                    "allow": [
                        r"command(regex:^([^\n]*\s)?python3\s+.*skills/quasar/scripts/.*)",
                        "command(git)",
                        "command(ls)",
                        "command(test)",
                        "command([)",
                        "command(echo)",
                        "command(true)",
                        f"read_file({real_state_dir}/)",
                    ]
                }
            }
        )
        prompt = (
            "Run this exact shell command: "
            "`ls -la ~/.gemini/quasar >/dev/null && test -d ~/.gemini/quasar && echo OK || echo FAIL` "
            "and reply ONLY with OK if it succeeded."
        )
        import subprocess
        proc = subprocess.run(
            [
                cli_bin,
                "--output-format=stream-json",
                "--mode=auto",
                f"--add-dir={real_state_dir}",
                f"--settings={settings}",
                f"--print={prompt}",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('"denied_actions"', proc.stdout)

    def test_extension_js_does_not_skip_agentapi_new_conversation_without_project_id(self) -> None:
        ext_text = (REPO_ROOT / "extension" / "extension.js").read_text(encoding="utf-8")
        self.assertNotIn("if (!env.ANTIGRAVITY_PROJECT_ID) {\n        tryDirectHttpFallback(null);", ext_text)
        self.assertIn("runAgentApi(newConvArgs,", ext_text)


if __name__ == "__main__":
    unittest.main()
