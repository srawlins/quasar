#!/usr/bin/env python3
"""Self-contained unit & mock-Gerrit integration test suite for Quasar's Gerrit support.

Runs completely offline in ~2 seconds using a local ThreadingHTTPServer that speaks Gerrit's
exact REST wire protocol (including `)]}'` XSSI prefixes, `/a/` authenticated routes, base64
patches & file contents, `?parent=1` base snapshots, threaded inline comments with `unresolved`,
multi-patchset `PS1 -> PS2` updates, Draft Comments, and `Set Review` submissions).
"""

import base64
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from typing import Any, Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "plugin", "skills", "quasar", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import collect_pr_context  # noqa: E402
import gerrit_adapter  # noqa: E402


def _gerrit_json_bytes(obj: Any) -> bytes:
    return (")]}'\n" + json.dumps(obj)).encode("utf-8")


class _MockGerritState:
    def __init__(self) -> None:
        self.current_ps = 1
        self.draft_seq = 0
        self.drafts: Dict[str, Dict[str, Any]] = {}
        self.submitted_reviews: List[Dict[str, Any]] = []
        self.auth_cookie = "secret-gitcookie-token"
        self.basic_auth_b64 = base64.b64encode(b"alice:http-secret").decode("ascii")

        self.base_calc_py = (
            "def divide(a: float, b: float) -> float:\n"
            "    return a / b\n"
        )
        self.ps1_calc_py = (
            "def divide(a: float, b: float) -> float:\n"
            "    # TODO: handle zero\n"
            "    return a / b\n\n"
            "def clamp_positive(x: float) -> float:\n"
            "    return x if x > 0 else 0.0\n"
        )
        self.ps2_calc_py = (
            "def divide(a: float, b: float) -> float:\n"
            "    if b == 0:\n"
            "        return 0.0\n"
            "    return a / b\n\n"
            "def clamp_positive(x: float) -> float:\n"
            "    return max(0.0, x)\n"
        )

    @property
    def rev1_sha(self) -> str:
        return "1111111111111111111111111111111111111111"

    @property
    def rev2_sha(self) -> str:
        return "2222222222222222222222222222222222222222"

    @property
    def base_sha(self) -> str:
        return "0000000000000000000000000000000000000000"

    @property
    def current_sha(self) -> str:
        return self.rev1_sha if self.current_ps == 1 else self.rev2_sha


class _MockGerritHandler(http.server.BaseHTTPRequestHandler):
    state: _MockGerritState

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _check_auth(self) -> bool:
        auth_hdr = self.headers.get("Authorization") or ""
        cookie_hdr = self.headers.get("Cookie") or ""
        if auth_hdr == f"Basic {self.state.basic_auth_b64}":
            return True
        if f"o={self.state.auth_cookie}" in cookie_hdr:
            return True
        return False

    def _send(self, code: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/a/"):
            if not self._check_auth():
                self._send(401, b"Unauthorized", "text/plain")
                return
            path = path[2:]

        if path == "/accounts/self":
            self._send(
                200,
                _gerrit_json_bytes({"_account_id": 7, "username": "alice", "name": "Alice Dev", "email": "alice@example.com"}),
            )
            return

        if path == "/changes/":
            item = {
                "id": "team%2Fcore-math~4242",
                "project": "team/core-math",
                "branch": "main",
                "_number": 4242,
                "subject": "feat(math): add clamp_positive and safe divide",
                "status": "NEW",
                "updated": "2026-11-17 15:00:00.000000000",
                "insertions": 6,
                "deletions": 0,
                "total_comment_count": 2,
                "unresolved_comment_count": 1,
                "owner": {"username": "bob", "name": "Bob Author", "email": "bob@example.com"},
                "current_revision": self.state.current_sha,
                "revisions": {
                    self.state.current_sha: {"_number": self.state.current_ps},
                },
            }
            self._send(200, _gerrit_json_bytes([item]))
            return

        # Normalize `/changes/team%2Fcore-math~4242...` or `/changes/4242...`
        for prefix in ("/changes/team%2Fcore-math~4242", "/changes/4242"):
            if path == prefix or path.startswith(prefix + "/"):
                sub = path[len(prefix) :]
                self._handle_change_subpath(sub, qs)
                return

        self._send(404, b"Not Found", "text/plain")

    def _handle_change_subpath(self, sub: str, qs: Dict[str, List[str]]) -> None:
        revs: Dict[str, Any] = {
            self.state.rev1_sha: {
                "_number": 1,
                "ref": "refs/changes/42/4242/1",
                "commit": {
                    "parents": [{"commit": self.state.base_sha}],
                    "subject": "feat(math): add clamp_positive and safe divide",
                    "message": "feat(math): add clamp_positive and safe divide\n\nAdds math helpers for clamping.\nChange-Id: I1234567890abcdef",
                },
            }
        }
        if self.state.current_ps >= 2:
            revs[self.state.rev2_sha] = {
                "_number": 2,
                "ref": "refs/changes/42/4242/2",
                "commit": {
                    "parents": [{"commit": self.state.base_sha}],
                    "subject": "feat(math): add clamp_positive and safe divide",
                    "message": "feat(math): add clamp_positive and safe divide\n\nGuards divide against zero.\nChange-Id: I1234567890abcdef",
                },
            }

        if sub == "":
            payload = {
                "id": "team%2Fcore-math~4242",
                "project": "team/core-math",
                "branch": "main",
                "change_id": "I1234567890abcdef",
                "_number": 4242,
                "subject": "feat(math): add clamp_positive and safe divide",
                "status": "NEW",
                "owner": {"username": "bob", "email": "bob@example.com"},
                "insertions": 6,
                "deletions": 0,
                "current_revision": self.state.current_sha,
                "revisions": revs,
                "messages": [
                    {"id": "m1", "message": "Uploaded patch set 1.", "date": "2026-11-17 12:00:00.000000000"},
                    {
                        "id": "m2",
                        "author": {"username": "carol"},
                        "message": "Patch Set 1: Code-Review-1\n\nPlease guard against division by zero.",
                        "date": "2026-11-17 12:05:00.000000000",
                    },
                ],
            }
            self._send(200, _gerrit_json_bytes(payload))
            return

        if sub == "/comments":
            comments = {
                "/COMMIT_MSG": [
                    {
                        "id": "c-msg-1",
                        "patch_set": 1,
                        "line": 1,
                        "updated": "2026-11-17 12:03:00.000000000",
                        "author": {"username": "carol"},
                        "message": "Nit: mention behavior when b == 0 in commit message.",
                        "unresolved": True,
                    }
                ],
                "src/calc.py": [
                    {
                        "id": "c-root-open",
                        "patch_set": 1,
                        "line": 3,
                        "commit_id": self.state.rev1_sha,
                        "updated": "2026-11-17 12:04:00.000000000",
                        "author": {"username": "carol"},
                        "message": "Should we return 0.0 or raise ValueError when b == 0?",
                        "unresolved": True,
                    },
                    {
                        "id": "c-root-resolved",
                        "patch_set": 1,
                        "line": 6,
                        "commit_id": self.state.rev1_sha,
                        "updated": "2026-11-17 12:04:30.000000000",
                        "author": {"username": "carol"},
                        "message": "Consider using max(0.0, x) here.",
                        "unresolved": True,
                    },
                    {
                        "id": "c-reply-resolved",
                        "patch_set": 1,
                        "line": 6,
                        "in_reply_to": "c-root-resolved",
                        "commit_id": self.state.rev1_sha,
                        "updated": "2026-11-17 12:10:00.000000000",
                        "author": {"username": "bob"},
                        "message": "Done in PS2!",
                        "unresolved": False,
                    },
                ],
            }
            self._send(200, _gerrit_json_bytes(comments))
            return

        for rev_key, content_txt in (
            (self.state.rev1_sha, self.state.ps1_calc_py),
            ("1", self.state.ps1_calc_py),
            (self.state.rev2_sha, self.state.ps2_calc_py),
            ("2", self.state.ps2_calc_py),
            ("current", self.state.ps1_calc_py if self.state.current_ps == 1 else self.state.ps2_calc_py),
        ):
            if sub == f"/revisions/{rev_key}/files":
                self._send(
                    200,
                    _gerrit_json_bytes(
                        {
                            "/COMMIT_MSG": {"status": "A", "lines_inserted": 9},
                            "src/calc.py": {"status": "M", "lines_inserted": 5, "lines_deleted": 0},
                        }
                    ),
                )
                return
            if sub == f"/revisions/{rev_key}/patch":
                if content_txt == self.state.ps1_calc_py:
                    diff_u = (
                        "From 1111111111111111111111111111111111111111 Mon Sep 17 00:00:00 2001\n"
                        "Subject: [PATCH] feat(math): add clamp_positive\n\n"
                        "diff --git a/src/calc.py b/src/calc.py\n"
                        "index 1111111..2222222 100644\n"
                        "--- a/src/calc.py\n"
                        "+++ b/src/calc.py\n"
                        "@@ -1,2 +1,6 @@\n"
                        " def divide(a: float, b: float) -> float:\n"
                        "+    # TODO: handle zero\n"
                        "     return a / b\n"
                        "+\n"
                        "+def clamp_positive(x: float) -> float:\n"
                        "+    return x if x > 0 else 0.0\n"
                    )
                else:
                    diff_u = (
                        "From 2222222222222222222222222222222222222222 Mon Sep 17 00:00:00 2001\n"
                        "Subject: [PATCH] feat(math): add clamp_positive\n\n"
                        "diff --git a/src/calc.py b/src/calc.py\n"
                        "index 1111111..3333333 100644\n"
                        "--- a/src/calc.py\n"
                        "+++ b/src/calc.py\n"
                        "@@ -1,2 +1,7 @@\n"
                        " def divide(a: float, b: float) -> float:\n"
                        "+    if b == 0:\n"
                        "+        return 0.0\n"
                        "     return a / b\n"
                        "+\n"
                        "+def clamp_positive(x: float) -> float:\n"
                        "+    return max(0.0, x)\n"
                    )
                self._send(200, base64.b64encode(diff_u.encode("utf-8")), "text/plain")
                return
            if sub == f"/revisions/{rev_key}/files/src%2Fcalc.py/content":
                raw = self.state.base_calc_py if qs.get("parent") == ["1"] else content_txt
                self._send(200, base64.b64encode(raw.encode("utf-8")), "text/plain")
                return

        self._send(404, b"Unknown revision subpath", "text/plain")

    def do_PUT(self) -> None:  # noqa: N802
        if not self.path.startswith("/a/") or not self._check_auth():
            self._send(401, b"Unauthorized", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if self.path.endswith("/drafts"):
            self.state.draft_seq += 1
            did = f"draft-{self.state.draft_seq}"
            saved = {"id": did, **payload}
            self.state.drafts[did] = saved
            self._send(201, _gerrit_json_bytes(saved))
            return
        self._send(404, b"Not Found", "text/plain")

    def do_DELETE(self) -> None:  # noqa: N802
        if not self.path.startswith("/a/") or not self._check_auth():
            self._send(401, b"Unauthorized", "text/plain")
            return
        if "/drafts/" in self.path:
            did = urllib.parse.unquote(self.path.rsplit("/drafts/", 1)[1])
            self.state.drafts.pop(did, None)
            self._send(204, b"", "text/plain")
            return
        self._send(404, b"Not Found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/a/") or not self._check_auth():
            self._send(401, b"Unauthorized", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if self.path.endswith("/review"):
            self.state.submitted_reviews.append(payload)
            self._send(200, _gerrit_json_bytes({"labels": payload.get("labels") or {}}))
            return
        self._send(404, b"Not Found", "text/plain")


class GerritAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = _MockGerritState()

        class BoundHandler(_MockGerritHandler):
            state = self.state

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BoundHandler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.tmp_home = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp_home.cleanup()

    def _isolated_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = self.tmp_home.name
        for k in (
            "GERRIT_HTTP_USER",
            "GERRIT_HTTP_PASSWORD",
            "GERRIT_AUTH_TOKEN",
            "GERRIT_COOKIE",
            "GIT_COOKIE_PATH",
            "QUASAR_SESSION_DIR",
            "QUASAR_STATE_DIR",
        ):
            env.pop(k, None)
        return env

    def test_url_parsing_variants_and_github_isolation(self) -> None:
        # 1. PolyGerrit nested project + patchset
        p1 = gerrit_adapter.parse_gerrit_url(
            "https://android-review.googlesource.com/c/platform/frameworks/base/+/2987654/3"
        )
        self.assertIsNotNone(p1)
        assert p1 is not None
        self.assertEqual(p1["baseUrl"], "https://android-review.googlesource.com")
        self.assertEqual(p1["project"], "platform/frameworks/base")
        self.assertEqual(p1["number"], 2987654)
        self.assertEqual(p1["patchSet"], 3)

        # 2. Subpath-mounted Gerrit (`/r/c/...`) + patchset comparison range `1..4` + file suffix
        p2 = gerrit_adapter.parse_gerrit_url(
            "https://git.eclipse.org/r/c/jdt/eclipse.jdt.core/+/205000/1..4/src/Main.java"
        )
        self.assertIsNotNone(p2)
        assert p2 is not None
        self.assertEqual(p2["baseUrl"], "https://git.eclipse.org/r")
        self.assertEqual(p2["project"], "jdt/eclipse.jdt.core")
        self.assertEqual(p2["number"], 205000)
        self.assertEqual(p2["basePatchSet"], 1)
        self.assertEqual(p2["patchSet"], 4)

        # 3. Short `/+/<num>` and legacy `/#/c/...`
        p3 = gerrit_adapter.parse_gerrit_url("https://go-review.googlesource.com/+/555123")
        assert p3 is not None and p3["number"] == 555123 and p3["project"] is None
        p4 = gerrit_adapter.parse_gerrit_url("https://review.opendev.org/#/c/openstack/nova/+/900123/2")
        assert p4 is not None and p4["project"] == "openstack/nova" and p4["patchSet"] == 2
        p5 = gerrit_adapter.parse_gerrit_url("https://go-review.googlesource.com/555123")
        assert p5 is not None and p5["number"] == 555123

        # 4. Never match GitHub, GitLab, Bitbucket, PR numbers, or local branches
        for non_gerrit in (
            "https://github.com/owner/repo/pull/123",
            "https://gitlab.com/group/proj/-/merge_requests/42",
            "owner/repo#123",
            "#123",
            "feature/add-plus/+/test",
            "HEAD",
        ):
            self.assertFalse(gerrit_adapter.is_gerrit_url(non_gerrit), f"Should not match {non_gerrit}")

    def test_gitcookies_httponly_and_expired_cookie_public_fallback(self) -> None:
        cookie_file = os.path.join(self.tmp_home.name, "test.gitcookies")
        # Write an INVALID `#HttpOnly_` cookie first -> public GET should still succeed via anonymous fallback!
        with open(cookie_file, "w", encoding="utf-8") as cf:
            cf.write("#HttpOnly_127.0.0.1\tFALSE\t/\tTRUE\t2147483647\to\twrong-cookie\n")

        prev_env = os.environ.get("GIT_COOKIE_PATH")
        os.environ["GIT_COOKIE_PATH"] = cookie_file
        try:
            auth = gerrit_adapter.resolve_gerrit_auth(self.base_url)
            self.assertTrue(auth["authenticated"])
            self.assertEqual(auth["source"], "gitcookies")
            # Anonymous fallback on 401 should transparently succeed for public GET!
            meta, _c, files, _d = gerrit_adapter.fetch_gerrit_change(
                f"{self.base_url}/c/team/core-math/+/4242",
                collect_pr_context.parse_first_changed_line,
                collect_pr_context.parse_all_hunks,
            )
            self.assertEqual(meta["number"], 4242)
            self.assertEqual(len(files), 1)

            # Now write the VALID `#HttpOnly_` cookie -> authenticated `/a/accounts/self` succeeds!
            with open(cookie_file, "w", encoding="utf-8") as cf:
                cf.write(f"#HttpOnly_127.0.0.1\tFALSE\t/\tTRUE\t2147483647\to\t{self.state.auth_cookie}\n")
            acct = gerrit_adapter.gerrit_api_request(self.base_url, "/accounts/self", require_auth=True)
            self.assertEqual(acct["username"], "alice")
        finally:
            if prev_env is None:
                os.environ.pop("GIT_COOKIE_PATH", None)
            else:
                os.environ["GIT_COOKIE_PATH"] = prev_env

    def test_end_to_end_collect_incremental_freshness_and_publish(self) -> None:
        env = self._isolated_env()
        ws_dir = os.path.join(self.tmp_home.name, "workspace")
        out_dir = os.path.join(self.tmp_home.name, "scratch")
        os.makedirs(ws_dir, exist_ok=True)
        cl_url = f"{self.base_url}/c/team/core-math/+/4242"

        # 1. Run `collect_pr_context.py --pr <gerrit_url>` on Patchset 1 (anonymous read!)
        collect_script = os.path.join(SCRIPTS_DIR, "collect_pr_context.py")
        res1 = subprocess.run(
            [sys.executable, collect_script, "--pr", cl_url, "--workspace-dir", ws_dir, "--output-dir", out_dir],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        summary1 = json.loads(res1.stdout)
        self.assertEqual(summary1["mode"], "pr")
        self.assertEqual(summary1["pr_metadata"]["provider"], "gerrit")
        self.assertEqual(summary1["pr_metadata"]["patchSet"], 1)
        self.assertEqual(summary1["pr_metadata"]["headSha"], self.state.rev1_sha)
        self.assertFalse(summary1["halt_llm_review"])

        # Verify base & head snapshots materialized cleanly
        with open(os.path.join(summary1["base_snapshot_root"], "src/calc.py"), encoding="utf-8") as bf:
            base_calc = bf.read()
        with open(os.path.join(summary1["head_snapshot_root"], "src/calc.py"), encoding="utf-8") as hf:
            head_calc = hf.read()
        self.assertEqual(base_calc, self.state.base_calc_py)
        self.assertEqual(head_calc, self.state.ps1_calc_py)

        # Verify inline comment threading & `unresolved: false` -> `addressed_or_refuted` triage!
        sess_path = summary1["active_session_path"]
        with open(sess_path, encoding="utf-8") as sf_in:
            sess1 = json.load(sf_in)
        threads_by_id = {t["id"]: t for t in sess1["threads"]}
        self.assertIn("gerrit-inline-c-root-open", threads_by_id)
        self.assertIn("gerrit-inline-c-root-resolved", threads_by_id)
        self.assertEqual(
            threads_by_id["gerrit-inline-c-root-resolved"]["triageStatus"],
            "addressed_or_refuted",
        )
        # Mark PS1 session as ready + add a staged AI finding so we can test incremental & publish!
        sess1["analysisStatus"] = "ready"
        sess1["threads"].append(
            {
                "id": "finding-div-zero",
                "kind": "ai_candidate",
                "severity": "BLOCKING",
                "status": "staged",
                "path": "src/calc.py",
                "startLine": 2,
                "endLine": 3,
                "title": "Guard against division by zero",
                "draftComment": "If `b == 0`, `a / b` raises `ZeroDivisionError`.",
            }
        )
        with open(sess_path, "w", encoding="utf-8") as sf:
            json.dump(sess1, sf, indent=2)

        # 2. Check `--check-existing` while still on PS1 -> `isUpToDate == True`
        watcher_script = os.path.join(SCRIPTS_DIR, "inbox_watcher.py")
        chk1 = json.loads(
            subprocess.run(
                [sys.executable, watcher_script, "--check-existing", cl_url],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertTrue(chk1["found"])
        self.assertTrue(chk1["isUpToDate"])
        self.assertEqual(chk1["provider"], "gerrit")

        # 3. Advance Gerrit server to Patchset 2! Verify stale-patchset detection + incremental delta review!
        self.state.current_ps = 2
        chk2 = json.loads(
            subprocess.run(
                [sys.executable, watcher_script, "--check-existing", cl_url],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertTrue(chk2["found"])
        self.assertFalse(chk2["isUpToDate"])
        self.assertEqual(chk2["cachedHeadSha"], self.state.rev1_sha)
        self.assertEqual(chk2["liveHeadSha"], self.state.rev2_sha)

        freshness = json.loads(
            subprocess.run(
                [sys.executable, watcher_script, "--check-session-freshness", "--workspace-dir", ws_dir],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertTrue(freshness["isStaleHead"])
        self.assertEqual(freshness["latestHeadSha"], self.state.rev2_sha)

        # Run incremental review `PS1 -> PS2`!
        res2 = subprocess.run(
            [
                sys.executable,
                collect_script,
                "--pr",
                cl_url,
                "--incremental-from",
                sess_path,
                "--workspace-dir",
                ws_dir,
                "--output-dir",
                out_dir,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        summary2 = json.loads(res2.stdout)
        self.assertTrue(summary2.get("is_incremental"))
        self.assertEqual(summary2["incremental_context"]["previousHeadSha"], self.state.rev1_sha)
        self.assertEqual(summary2["incremental_context"]["newHeadSha"], self.state.rev2_sha)
        self.assertEqual(len(summary2["incremental_context"]["deltaFiles"]), 1)

        # 4. Configure Gerrit HTTP auth & test `PENDING` draft upload, draft replacement, and `APPROVE` review!
        post_script = os.path.join(SCRIPTS_DIR, "post_pending_review.py")
        auth_res = json.loads(
            subprocess.run(
                [sys.executable, post_script, "--set-gerrit-auth", self.base_url, "alice", "http-secret"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertTrue(auth_res["ok"])
        self.assertEqual(auth_res["account"]["username"], "alice")

        # Stage a comment on PS2 and publish as `PENDING` (Gerrit Draft)
        with open(sess_path, encoding="utf-8") as sf2_in:
            sess2 = json.load(sf2_in)
        sess2["threads"].append(
            {
                "id": "finding-ps2-nit",
                "kind": "ai_candidate",
                "severity": "NIT",
                "status": "staged",
                "path": "src/calc.py",
                "startLine": 2,
                "endLine": 4,
                "title": "Document 0.0 fallback",
                "draftComment": "Nit: add a docstring noting `divide(a, 0)` returns `0.0`.",
            }
        )
        with open(sess_path, "w", encoding="utf-8") as sf:
            json.dump(sess2, sf, indent=2)

        pub_draft1 = json.loads(
            subprocess.run(
                [
                    sys.executable,
                    post_script,
                    "--from-session",
                    "--event",
                    "PENDING",
                    "--summary-body",
                    "Overall looks good!",
                    "--workspace-dir",
                    ws_dir,
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertEqual(pub_draft1["status"], "pending_review_created")
        self.assertEqual(len(self.state.drafts), 2)  # 1 inline + 1 patchset-level summary draft!

        # Re-exporting `PENDING` replaces the prior drafts cleanly (still 2 drafts, no duplicates!)
        pub_draft2 = json.loads(
            subprocess.run(
                [
                    sys.executable,
                    post_script,
                    "--from-session",
                    "--event",
                    "PENDING",
                    "--summary-body",
                    "Updated summary!",
                    "--workspace-dir",
                    ws_dir,
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertEqual(pub_draft2["status"], "pending_review_updated")
        self.assertEqual(len(self.state.drafts), 2)

        # Submitting `APPROVE` deletes the temporary drafts and posts `Code-Review: +1` + inline comments!
        pub_approve = json.loads(
            subprocess.run(
                [
                    sys.executable,
                    post_script,
                    "--from-session",
                    "--event",
                    "APPROVE",
                    "--summary-body",
                    "LGTM!",
                    "--workspace-dir",
                    ws_dir,
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertEqual(pub_approve["status"], "review_published")
        self.assertEqual(len(self.state.drafts), 0)
        self.assertEqual(len(self.state.submitted_reviews), 1)
        posted = self.state.submitted_reviews[0]
        self.assertEqual(posted["labels"], {"Code-Review": 1})
        self.assertEqual(posted["message"], "LGTM!")
        self.assertIn("src/calc.py", posted["comments"])

        # 5. Optional `gerritHosts` Inbox sync (0 GitHub token needed when `gerritHosts` is configured!)
        subprocess.run(
            [sys.executable, watcher_script, "--configure", "--gerrit-hosts", self.base_url],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        sync_out = json.loads(
            subprocess.run(
                [sys.executable, watcher_script, "--sync-now"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertTrue(sync_out["ok"])
        items = sync_out["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["provider"], "gerrit")
        self.assertEqual(items[0]["number"], 4242)


if __name__ == "__main__":
    unittest.main()
