#!/usr/bin/env python3
"""Background Auto-Review Daemon & Multi-PR Inbox Manager for Quasar.

Polls GitHub for:
  1. Incoming PRs requesting the user's review (`review-requested:@me`)
  2. User-authored open PRs with new external review comments or `CHANGES_REQUESTED`
  3. Optional user-configured `watchedRepos`

Key design & safety properties:
  - Isolated staging storage (`~/.gemini/quasar/inbox/items/<id>/`): background pre-reviews
    pass `QUASAR_SESSION_DIR` / `--session-dir` so they NEVER overwrite any window's live
    `active_session.json` while the user is mid-review. Clicking an Inbox item swaps its
    pre-computed session into the active workspace in ~0ms.
  - Zero-token GitHub polling: polling and fingerprinting run purely in Python via GitHub's
    REST API (`0` LLM tokens when nothing changed).
  - Strict token-consumption safeguards (all user-configurable):
      * `enabled`: `False` by default (opt-in)
      * `mode`: `"auto_precompute"` or `"sync_queue_only"` (0-token queue view)
      * `maxConcurrency`: `1` (only one background review runs at a time)
      * `maxReviewsPerCycle`: `1` (prevents a 20+ PR burst on initial setup; trickles 1 per cycle)
      * `maxReviewsPerDay`: `6` (daily auto-review cap; `0` = unlimited)
      * `onlyUpdatedWithinDays`: `14` (skips auto-burning tokens on stale PRs; `0` = no cutoff)
  - Automatic Security Gate (`security_gate.py`): runs `collect_pr_context.py` in Python
    first; if `halt_llm_review` triggers, marks the PR `quarantined` in the Inbox without
    ever invoking `agy`.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from collect_pr_context import (
    HISTORY_STATE_DIR,
    REVIEW_STATE_DIR,
    WORKSPACES_STATE_DIR,
    archive_review_session,
    auto_detect_repo_dir,
    get_github_token,
    get_session_paths,
    infer_owner_repo,
    is_github_pr_arg,
    is_pid_alive,
    load_stored_github_auth,
    materialize_snapshots,
    render_cliffs_notes_markdown,
    resolve_workspace_root,
)

INBOX_DIR = os.path.join(REVIEW_STATE_DIR, "inbox")
INBOX_SETTINGS_PATH = os.path.join(INBOX_DIR, "settings.json")
INBOX_STATE_PATH = os.path.join(INBOX_DIR, "state.json")
INBOX_DAEMON_PATH = os.path.join(INBOX_DIR, "daemon.json")
INBOX_LOG_PATH = os.path.join(INBOX_DIR, "daemon.log")
INBOX_ITEMS_DIR = os.path.join(INBOX_DIR, "items")

DEFAULT_INBOX_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "mode": "auto_precompute",  # "auto_precompute" | "sync_queue_only"
    "watchReviewRequested": True,
    "watchAuthoredPrs": True,
    "watchedRepos": [],
    "restrictToWatchedRepos": False,
    "includeDrafts": False,
    "effort": "high",  # "low" | "medium" | "high"
    "commentsOnly": False,
    "pollIntervalMinutes": 15,
    "maxConcurrency": 1,
    "maxReviewsPerCycle": 1,
    "maxReviewsPerDay": 6,
    "onlyUpdatedWithinDays": 14,
    "incrementalUpdates": True,
    "notifyWhenReady": True,
}


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _today_local_str() -> str:
    return datetime.date.today().isoformat()


def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def normalize_inbox_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(DEFAULT_INBOX_SETTINGS)
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw:
        out["enabled"] = bool(raw["enabled"])
    if raw.get("mode") in ("auto_precompute", "sync_queue_only"):
        out["mode"] = str(raw["mode"])
    if "watchReviewRequested" in raw:
        out["watchReviewRequested"] = bool(raw["watchReviewRequested"])
    if "watchAuthoredPrs" in raw:
        out["watchAuthoredPrs"] = bool(raw["watchAuthoredPrs"])
    if "watchedRepos" in raw:
        val = raw["watchedRepos"]
        if isinstance(val, str):
            repos = [r.strip() for r in re.split(r"[,\s]+", val) if "/" in r.strip()]
        elif isinstance(val, list):
            repos = [str(r).strip() for r in val if "/" in str(r).strip()]
        else:
            repos = []
        out["watchedRepos"] = list(dict.fromkeys(repos))
    if "restrictToWatchedRepos" in raw:
        out["restrictToWatchedRepos"] = bool(raw["restrictToWatchedRepos"])
    if "includeDrafts" in raw:
        out["includeDrafts"] = bool(raw["includeDrafts"])
    if str(raw.get("effort") or "").lower() in ("low", "medium", "high"):
        out["effort"] = str(raw["effort"]).lower()
    if "commentsOnly" in raw:
        out["commentsOnly"] = bool(raw["commentsOnly"])
    if "pollIntervalMinutes" in raw:
        try:
            out["pollIntervalMinutes"] = max(2, min(720, int(raw["pollIntervalMinutes"])))
        except Exception:
            pass
    if "maxConcurrency" in raw:
        try:
            out["maxConcurrency"] = max(1, min(4, int(raw["maxConcurrency"])))
        except Exception:
            pass
    if "maxReviewsPerCycle" in raw:
        try:
            out["maxReviewsPerCycle"] = max(0, min(50, int(raw["maxReviewsPerCycle"])))
        except Exception:
            pass
    if "maxReviewsPerDay" in raw:
        try:
            out["maxReviewsPerDay"] = max(0, min(200, int(raw["maxReviewsPerDay"])))
        except Exception:
            pass
    if "onlyUpdatedWithinDays" in raw:
        try:
            out["onlyUpdatedWithinDays"] = max(0, min(365, int(raw["onlyUpdatedWithinDays"])))
        except Exception:
            pass
    if "incrementalUpdates" in raw:
        out["incrementalUpdates"] = bool(raw["incrementalUpdates"])
    if "notifyWhenReady" in raw:
        out["notifyWhenReady"] = bool(raw["notifyWhenReady"])
    return out


def load_inbox_settings() -> Dict[str, Any]:
    os.makedirs(INBOX_DIR, exist_ok=True)
    if not os.path.isfile(INBOX_SETTINGS_PATH):
        return dict(DEFAULT_INBOX_SETTINGS)
    try:
        with open(INBOX_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return normalize_inbox_settings(json.load(f))
    except Exception:
        return dict(DEFAULT_INBOX_SETTINGS)


def save_inbox_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    current = load_inbox_settings()
    merged_raw = dict(current)
    merged_raw.update(updates or {})
    norm = normalize_inbox_settings(merged_raw)
    norm["updatedAt"] = _now_iso()
    _atomic_write_json(INBOX_SETTINGS_PATH, norm)
    return norm


def load_inbox_state() -> Dict[str, Any]:
    os.makedirs(INBOX_ITEMS_DIR, exist_ok=True)
    base: Dict[str, Any] = {
        "version": 1,
        "lastSyncedAt": None,
        "lastCycleAt": None,
        "githubLogin": "",
        "budgetDate": _today_local_str(),
        "reviewsRunToday": 0,
        "lastSyncError": "",
        "items": {},
    }
    if os.path.isfile(INBOX_STATE_PATH):
        try:
            with open(INBOX_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                base.update(data)
        except Exception:
            pass
    today = _today_local_str()
    if base.get("budgetDate") != today:
        base["budgetDate"] = today
        base["reviewsRunToday"] = 0
    if not isinstance(base.get("items"), dict):
        base["items"] = {}
    return base


def save_inbox_state(state: Dict[str, Any]) -> None:
    state["updatedAt"] = _now_iso()
    _atomic_write_json(INBOX_STATE_PATH, state)


def load_daemon_status() -> Dict[str, Any]:
    if not os.path.isfile(INBOX_DAEMON_PATH):
        return {"running": False, "pid": None}
    try:
        with open(INBOX_DAEMON_PATH, "r", encoding="utf-8") as f:
            info = json.load(f)
        pid = info.get("pid")
        alive = bool(pid and is_pid_alive(pid))
        info["running"] = alive
        if not alive:
            info["activeItemIds"] = []
        return info
    except Exception:
        return {"running": False, "pid": None}


def save_daemon_status(info: Dict[str, Any]) -> None:
    info["updatedAt"] = _now_iso()
    _atomic_write_json(INBOX_DAEMON_PATH, info)


def find_agy_binary() -> Optional[str]:
    for cand in [
        os.environ.get("AGY_BIN") or "",
        os.path.expanduser("~/.gemini/bin/agy"),
        "/opt/homebrew/bin/agy",
        "/usr/local/bin/agy",
        shutil.which("agy") or "",
    ]:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _gh_api_get(path_or_url: str, token: str, timeout: float = 20.0) -> Any:
    url = (
        path_or_url
        if path_or_url.startswith("https://")
        else f"https://api.github.com/{path_or_url.lstrip('/')}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Quasar-Inbox-Watcher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def resolve_github_login(token: str, cached_login: str = "") -> str:
    stored = (load_stored_github_auth().get("login") or "").strip()
    if stored:
        return stored
    if cached_login:
        return cached_login
    data = _gh_api_get("/user", token, timeout=12.0)
    return str(data.get("login") or "").strip()


def _parse_iso_dt(val: str) -> Optional[datetime.datetime]:
    if not val:
        return None
    try:
        return datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


def sync_github_queue(
    settings: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Polls GitHub REST API for open PRs matching the user's Inbox settings (0 LLM tokens)."""
    cfg = settings or load_inbox_settings()
    st = state or load_inbox_state()
    token = get_github_token()
    if not token:
        st["lastSyncError"] = (
            "No GitHub token configured. Connect your GitHub API key in Quasar to sync your PR Inbox."
        )
        save_inbox_state(st)
        return {"ok": False, "error": st["lastSyncError"], "state": st}

    try:
        login = resolve_github_login(token, str(st.get("githubLogin") or ""))
    except Exception as exc:
        st["lastSyncError"] = f"GitHub authentication failed: {exc}"
        save_inbox_state(st)
        return {"ok": False, "error": st["lastSyncError"], "state": st}

    if not login:
        st["lastSyncError"] = "Could not determine GitHub username from token."
        save_inbox_state(st)
        return {"ok": False, "error": st["lastSyncError"], "state": st}

    st["githubLogin"] = login
    watched_repos: List[str] = cfg.get("watchedRepos") or []
    restrict_repos = bool(cfg.get("restrictToWatchedRepos") and watched_repos)
    draft_qual = "" if cfg.get("includeDrafts") else " -is:draft"
    repo_qual = " " + " ".join(f"repo:{r}" for r in watched_repos[:15]) if restrict_repos else ""

    queries: List[Tuple[str, str]] = []
    if cfg.get("watchReviewRequested", True):
        queries.append(("reviewer", f"is:pr is:open review-requested:{login}{draft_qual}{repo_qual}"))
    if cfg.get("watchAuthoredPrs", True):
        queries.append(("author", f"is:pr is:open author:{login}{draft_qual}{repo_qual}"))
    if watched_repos and not restrict_repos:
        extra_repo_q = " ".join(f"repo:{r}" for r in watched_repos[:12])
        queries.append(("watched_repo", f"is:pr is:open -author:{login}{draft_qual} {extra_repo_q}"))

    discovered: Dict[str, Tuple[str, str, int, str]] = {}
    try:
        for role, q in queries:
            enc_q = urllib.parse.quote(q)
            search_res = _gh_api_get(
                f"/search/issues?q={enc_q}&sort=updated&order=desc&per_page=30",
                token,
            )
            for issue in search_res.get("items") or []:
                repo_api_url = str(issue.get("repository_url") or "")
                m_repo = re.search(r"/repos/([^/]+)/([^/]+)$", repo_api_url)
                pr_num = int(issue.get("number") or 0)
                if not m_repo or pr_num <= 0:
                    continue
                owner, repo = m_repo.group(1), m_repo.group(2)
                item_id = f"{owner}-{repo}-pr-{pr_num}"
                # Keep `reviewer` or `author` role ahead of generic `watched_repo`
                if item_id not in discovered or discovered[item_id][3] == "watched_repo":
                    discovered[item_id] = (owner, repo, pr_num, role)
    except Exception as exc:
        st["lastSyncError"] = f"GitHub search failed: {exc}"
        save_inbox_state(st)
        return {"ok": False, "error": st["lastSyncError"], "state": st}

    items_map: Dict[str, Any] = st.setdefault("items", {})
    open_ids = set(discovered.keys())

    # Mark previously tracked open items that were closed/merged or unassigned
    for old_id, old_item in list(items_map.items()):
        if old_id not in open_ids and old_item.get("openInQueue", True):
            old_item["openInQueue"] = False

    def _fetch_pr_detail(entry: Tuple[str, Tuple[str, str, int, str]]) -> Tuple[str, Optional[Dict[str, Any]]]:
        iid, (own, rep, num, role) = entry
        try:
            pr_obj = _gh_api_get(f"/repos/{own}/{rep}/pulls/{num}", token)
            reviews_list: List[Dict[str, Any]] = []
            if role == "author":
                try:
                    rev_res = _gh_api_get(f"/repos/{own}/{rep}/pulls/{num}/reviews?per_page=40", token)
                    if isinstance(rev_res, list):
                        reviews_list = rev_res
                except Exception:
                    reviews_list = []
            return iid, {"pr": pr_obj, "role": role, "owner": own, "repo": rep, "reviews": reviews_list}
        except Exception:
            return iid, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        detail_results = list(pool.map(_fetch_pr_detail, list(discovered.items())))

    login_lower = login.lower()
    for item_id, detail in detail_results:
        if not detail:
            continue
        pr_obj = detail["pr"]
        role = detail["role"]
        owner = detail["owner"]
        repo = detail["repo"]
        pr_num = int(pr_obj.get("number") or 0)
        if pr_obj.get("draft") and not cfg.get("includeDrafts"):
            if item_id in items_map:
                items_map[item_id]["openInQueue"] = False
            continue

        head_sha = str((pr_obj.get("head") or {}).get("sha") or "")
        head_ref = str((pr_obj.get("head") or {}).get("ref") or "")
        base_ref = str((pr_obj.get("base") or {}).get("ref") or "")
        author_login = str((pr_obj.get("user") or {}).get("login") or "")
        additions = int(pr_obj.get("additions") or 0)
        deletions = int(pr_obj.get("deletions") or 0)
        changed_files = int(pr_obj.get("changed_files") or 0)
        review_comments_cnt = int(pr_obj.get("review_comments") or 0)
        issue_comments_cnt = int(pr_obj.get("comments") or 0)
        updated_at = str(pr_obj.get("updated_at") or _now_iso())
        html_url = str(pr_obj.get("html_url") or f"https://github.com/{owner}/{repo}/pull/{pr_num}")
        title = str(pr_obj.get("title") or f"PR #{pr_num}")

        external_reviews = [
            r
            for r in (detail.get("reviews") or [])
            if str((r.get("user") or {}).get("login") or "").lower() not in ("", login_lower)
            and str(r.get("state") or "").upper() in ("CHANGES_REQUESTED", "COMMENTED", "APPROVED")
        ]
        changes_requested = any(
            str(r.get("state") or "").upper() == "CHANGES_REQUESTED" for r in external_reviews
        )
        latest_rev_id = str(external_reviews[-1].get("id") or "") if external_reviews else ""

        if role == "author":
            has_external_feedback = (
                review_comments_cnt > 0 or changes_requested or len(external_reviews) > 0
            )
            fingerprint = f"{head_sha}:rc={review_comments_cnt}:ic={issue_comments_cnt}:rv={latest_rev_id}"
            bucket_hint = "author_action_needed" if has_external_feedback else "waiting_on_reviewers"
        else:
            has_external_feedback = True
            fingerprint = head_sha
            bucket_hint = "reviewer"

        existing = items_map.get(item_id) or {}
        prev_analyzed_fp = str(existing.get("analyzedFingerprint") or "")
        prev_reviewed_sha = str(existing.get("reviewedHeadSha") or "")
        prev_status = str(existing.get("status") or "queued")

        item_dir = os.path.join(INBOX_ITEMS_DIR, item_id)
        has_ready_session = os.path.isfile(os.path.join(item_dir, "active_session.json"))

        prev_deleted_sha = str(existing.get("deletedAtSha") or "")
        updated_since_review = bool(
            (prev_reviewed_sha and prev_reviewed_sha != head_sha)
            or (prev_status == "deleted" and prev_deleted_sha and prev_deleted_sha != head_sha)
        )

        if prev_status == "analyzing":
            new_status = "analyzing"
        elif prev_status == "deleted":
            new_status = "deleted"
        elif bucket_hint == "waiting_on_reviewers" and prev_analyzed_fp != fingerprint:
            new_status = "waiting_on_reviewers"
        elif prev_analyzed_fp == fingerprint and has_ready_session and prev_status in ("ready", "quarantined"):
            new_status = prev_status
        elif prev_reviewed_sha == head_sha and role != "author":
            new_status = "waiting_on_author"
        else:
            new_status = "queued"

        merged_item: Dict[str, Any] = {
            **existing,
            "id": item_id,
            "owner": owner,
            "repo": repo,
            "number": pr_num,
            "title": title,
            "url": html_url,
            "author": author_login,
            "role": role,
            "bucketHint": bucket_hint,
            "baseRefName": base_ref,
            "headRefName": head_ref,
            "headSha": head_sha,
            "additions": additions,
            "deletions": deletions,
            "changedFilesCount": changed_files,
            "reviewCommentsCount": review_comments_cnt,
            "issueCommentsCount": issue_comments_cnt,
            "changesRequested": changes_requested,
            "updatedAt": updated_at,
            "currentFingerprint": fingerprint,
            "updatedSinceLastReview": updated_since_review,
            "openInQueue": True,
            "status": new_status,
            "sessionDir": item_dir,
        }
        if new_status == "queued":
            adopt_completed_session_into_inbox(
                merged_item,
                owner=owner,
                repo=repo,
                pr_num=pr_num,
                head_sha=head_sha,
                fingerprint=fingerprint,
                role=role,
                expected_review_comments=review_comments_cnt,
            )
        items_map[item_id] = merged_item

    st["lastSyncedAt"] = _now_iso()
    st["lastSyncError"] = ""
    save_inbox_state(st)
    return {"ok": True, "login": login, "discoveredCount": len(discovered), "state": st}


def _is_completed_review_session(sess: Any) -> bool:
    if not isinstance(sess, dict):
        return False
    sg = sess.get("securityGate")
    if isinstance(sg, dict) and sg.get("status") == "blocked" and not sg.get("overridden"):
        return False
    status = str(sess.get("analysisStatus") or "").strip().lower()
    if status in ("analyzing", "initializing", "quarantined"):
        return False
    if status == "ready":
        return True
    cn = sess.get("cliffsNotes") or {}
    return bool(cn.get("tldr") or sess.get("chapters"))


def _session_matches_pr(sess: Any, owner: str, repo: str, pr_num: int) -> bool:
    if not isinstance(sess, dict):
        return False
    pr = sess.get("pr") or {}
    try:
        s_num = int(pr.get("number") or 0)
    except Exception:
        s_num = 0
    if s_num != int(pr_num):
        return False
    s_owner = str(pr.get("owner") or "").strip().lower()
    s_repo = str(pr.get("repo") or "").strip().lower()
    return s_owner == owner.strip().lower() and s_repo == repo.strip().lower()


def _scan_completed_sessions_for_pr(
    owner: str,
    repo: str,
    pr_num: int,
    include_inbox: bool = True,
) -> List[Dict[str, Any]]:
    """Scans Inbox items, active workspaces, and review history for completed sessions matching owner/repo#pr_num."""
    found: List[Dict[str, Any]] = []
    seen_paths = set()

    def _add_candidate(path: str, source: str, source_label: str, item_id: str = "") -> None:
        real_p = os.path.realpath(path)
        if real_p in seen_paths or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                sess = json.load(f)
        except Exception:
            return
        if not _session_matches_pr(sess, owner, repo, pr_num):
            return
        if not _is_completed_review_session(sess):
            return
        seen_paths.add(real_p)
        pr_meta = sess.get("pr") or {}
        threads = [t for t in (sess.get("threads") or []) if t.get("status") != "dismissed"]
        ai_findings = [
            t for t in threads if t.get("kind") in ("ai_candidate", "user_staged") and t.get("status") != "fixed"
        ]
        blocking = [t for t in ai_findings if "BLOCK" in str(t.get("severity") or "").upper()]
        gh_existing_count = sum(1 for t in (sess.get("threads") or []) if t.get("kind") == "github_existing")
        cn = sess.get("cliffsNotes") or {}
        ts = str(sess.get("publishedAt") or sess.get("updatedAt") or sess.get("createdAt") or "")
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0.0
        found.append(
            {
                "source": source,
                "sourceLabel": source_label,
                "itemId": item_id or f"{owner}-{repo}-pr-{pr_num}",
                "sessionPath": path,
                "session": sess,
                "headSha": str(pr_meta.get("headSha") or ""),
                "baseSha": str(pr_meta.get("baseSha") or ""),
                "title": str(pr_meta.get("title") or ""),
                "prUrl": str(pr_meta.get("url") or f"https://github.com/{owner}/{repo}/pull/{pr_num}"),
                "effort": str(sess.get("effort") or "high").lower(),
                "commentsOnly": bool(sess.get("commentsOnly", False)),
                "findingsCount": len(ai_findings),
                "blockingCount": len(blocking),
                "chaptersCount": len(sess.get("chapters") or []),
                "ghExistingThreadsCount": gh_existing_count,
                "tldr": str(cn.get("tldr") or "")[:240],
                "completedAt": ts,
                "mtime": mtime,
            }
        )

    if include_inbox:
        default_iid = f"{owner}-{repo}-pr-{pr_num}"
        _add_candidate(
            os.path.join(INBOX_ITEMS_DIR, default_iid, "active_session.json"),
            "inbox",
            "Auto-Review Inbox",
            default_iid,
        )
        if os.path.isdir(INBOX_ITEMS_DIR):
            st = load_inbox_state()
            for iid, it in (st.get("items") or {}).items():
                if (
                    str(it.get("owner") or "").lower() == owner.lower()
                    and str(it.get("repo") or "").lower() == repo.lower()
                    and int(it.get("number") or 0) == int(pr_num)
                ):
                    s_dir = str(it.get("sessionDir") or os.path.join(INBOX_ITEMS_DIR, iid))
                    _add_candidate(os.path.join(s_dir, "active_session.json"), "inbox", "Auto-Review Inbox", iid)

    if os.path.isdir(WORKSPACES_STATE_DIR):
        for entry in os.listdir(WORKSPACES_STATE_DIR):
            _add_candidate(
                os.path.join(WORKSPACES_STATE_DIR, entry, "active_session.json"),
                "workspace",
                "Active Workspace",
            )

    if os.path.isdir(HISTORY_STATE_DIR):
        direct_hist = os.path.join(HISTORY_STATE_DIR, f"{owner}-{repo}-pr-{pr_num}", "session.json")
        _add_candidate(direct_hist, "history", "Review History")
        for entry in os.listdir(HISTORY_STATE_DIR):
            _add_candidate(
                os.path.join(HISTORY_STATE_DIR, entry, "session.json"),
                "history",
                "Review History",
            )

    return found


def adopt_completed_session_into_inbox(
    item_dict: Dict[str, Any],
    owner: str,
    repo: str,
    pr_num: int,
    head_sha: str,
    fingerprint: str,
    role: str = "reviewer",
    expected_review_comments: int = 0,
) -> bool:
    """If the user already reviewed this exact PR + headSha manually (in workspace or history),
    adopts that completed session into the Inbox item staging dir for 0 LLM tokens!
    """
    if not head_sha:
        return False
    candidates = _scan_completed_sessions_for_pr(owner, repo, pr_num, include_inbox=False)
    matching = [c for c in candidates if c.get("headSha") == head_sha]
    if not matching:
        return False
    matching.sort(key=lambda c: float(c.get("mtime") or 0.0), reverse=True)
    best = matching[0]
    if role == "author" and expected_review_comments > 0:
        # Ensure the manually-run session didn't precede newly posted external review comments
        if int(best.get("ghExistingThreadsCount") or 0) == 0:
            return False

    item_id = str(item_dict.get("id") or f"{owner}-{repo}-pr-{pr_num}")
    item_dir = str(item_dict.get("sessionDir") or os.path.join(INBOX_ITEMS_DIR, item_id))
    os.makedirs(item_dir, exist_ok=True)

    sess_copy = dict(best["session"])
    sess_copy.pop("windowId", None)
    sess_copy.pop("windowPid", None)
    sess_copy.pop("workspaceDir", None)
    sess_copy["stateDir"] = item_dir
    dst_sess = os.path.join(item_dir, "active_session.json")
    _atomic_write_json(dst_sess, sess_copy)

    src_dir = os.path.dirname(os.path.abspath(str(best["sessionPath"])))
    for extra_name in ("cliffs_notes.md", "pr_context.json", "pr.diff"):
        src_extra = os.path.join(src_dir, extra_name)
        if os.path.isfile(src_extra):
            try:
                shutil.copy2(src_extra, os.path.join(item_dir, extra_name))
            except Exception:
                pass

    item_dict["status"] = "ready"
    item_dict["analyzedFingerprint"] = fingerprint
    item_dict["analyzedEffort"] = best.get("effort") or "high"
    item_dict["completedAt"] = best.get("completedAt") or _now_iso()
    item_dict["adoptedFromManualReview"] = True
    item_dict["unread"] = False
    item_dict.update(_extract_session_metrics(dst_sess))
    return True


def sync_published_session_to_inbox(
    session_dict: Dict[str, Any],
    md_content: Optional[str] = None,
) -> bool:
    """Mirrors a newly published manual GitHub PR review into the Inbox item cache if tracked,
    so re-running a review manually also refreshes its Inbox entry and prevents duplicate daemon runs.
    """
    if not _is_completed_review_session(session_dict):
        return False
    pr = session_dict.get("pr") or {}
    owner = str(pr.get("owner") or "").strip()
    repo = str(pr.get("repo") or "").strip()
    try:
        pr_num = int(pr.get("number") or 0)
    except Exception:
        pr_num = 0
    if not owner or owner == "local" or not repo or pr_num <= 0:
        return False
    if not os.path.isfile(INBOX_STATE_PATH):
        return False

    st = load_inbox_state()
    items = st.get("items") or {}
    target_iid = None
    for iid, it in items.items():
        if (
            str(it.get("owner") or "").lower() == owner.lower()
            and str(it.get("repo") or "").lower() == repo.lower()
            and int(it.get("number") or 0) == pr_num
        ):
            target_iid = iid
            break
    if not target_iid:
        return False

    it = items[target_iid]
    item_dir = str(it.get("sessionDir") or os.path.join(INBOX_ITEMS_DIR, target_iid))
    os.makedirs(item_dir, exist_ok=True)
    sess_copy = dict(session_dict)
    sess_copy.pop("windowId", None)
    sess_copy.pop("windowPid", None)
    sess_copy.pop("workspaceDir", None)
    sess_copy["stateDir"] = item_dir
    dst_sess = os.path.join(item_dir, "active_session.json")
    _atomic_write_json(dst_sess, sess_copy)
    if md_content:
        try:
            with open(os.path.join(item_dir, "cliffs_notes.md"), "w", encoding="utf-8") as mf:
                mf.write(md_content)
        except Exception:
            pass

    head_sha = str(pr.get("headSha") or "")
    if head_sha:
        it["headSha"] = head_sha
        if it.get("role") != "author":
            it["currentFingerprint"] = head_sha
        it["analyzedFingerprint"] = it.get("currentFingerprint") or head_sha
    it["status"] = "ready"
    it["analyzedEffort"] = str(session_dict.get("effort") or "high").lower()
    it["completedAt"] = _now_iso()
    it["unread"] = False
    it.pop("lastError", None)
    it.update(_extract_session_metrics(dst_sess))
    save_inbox_state(st)
    return True


def find_existing_completed_branch_review(
    branch_arg: str,
    repo_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Checks whether a local git branch in `repo_dir` already has a completed review in Workspace or History."""
    r_dir = os.path.realpath(os.path.expanduser(repo_dir or os.getcwd()))
    if not os.path.isdir(os.path.join(r_dir, ".git")):
        return {"ok": True, "found": False}
    raw_ref = (branch_arg or "HEAD").strip()
    if "..." in raw_ref:
        raw_ref = raw_ref.split("...", 1)[1].strip() or "HEAD"
    elif ".." in raw_ref:
        raw_ref = raw_ref.split("..", 1)[1].strip() or "HEAD"

    try:
        cur_b = subprocess.run(
            ["git", "branch", "--show-current"], cwd=r_dir, capture_output=True, text=True, timeout=4
        ).stdout.strip()
        if raw_ref == "HEAD":
            branch_name = cur_b or "HEAD"
        else:
            ab = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", raw_ref], cwd=r_dir, capture_output=True, text=True, timeout=4
            )
            branch_name = ab.stdout.strip() if ab.returncode == 0 and ab.stdout.strip() else raw_ref
        sha_res = subprocess.run(
            ["git", "rev-parse", raw_ref], cwd=r_dir, capture_output=True, text=True, timeout=4
        )
        if sha_res.returncode != 0 or not sha_res.stdout.strip():
            return {"ok": True, "found": False}
        live_sha = sha_res.stdout.strip()
    except Exception:
        return {"ok": True, "found": False}

    repo_name = os.path.basename(r_dir)
    candidates: List[Dict[str, Any]] = []
    seen_real = set()

    def _scan_branch_path(p: str, src: str, src_label: str) -> None:
        rp = os.path.realpath(p)
        if rp in seen_real or not os.path.isfile(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as sf:
                sess = json.load(sf)
        except Exception:
            return
        if not _is_completed_review_session(sess):
            return
        pr = sess.get("pr") or {}
        if pr.get("number") and str(pr.get("owner") or "") != "local":
            return
        s_repo = str(pr.get("repo") or "").strip().lower()
        s_branch = str(pr.get("headBranch") or pr.get("headRefName") or "").replace(" + working tree", "").strip()
        if s_repo != repo_name.lower() or s_branch != branch_name:
            return
        seen_real.add(rp)
        threads = [t for t in (sess.get("threads") or []) if t.get("status") != "dismissed"]
        ai_findings = [
            t for t in threads if t.get("kind") in ("ai_candidate", "user_staged") and t.get("status") != "fixed"
        ]
        cn = sess.get("cliffsNotes") or {}
        try:
            mtime = os.path.getmtime(p)
        except Exception:
            mtime = 0.0
        candidates.append(
            {
                "source": src,
                "sourceLabel": src_label,
                "sessionPath": p,
                "session": sess,
                "headSha": str(pr.get("headSha") or ""),
                "title": str(pr.get("title") or f"{repo_name}@{branch_name}"),
                "effort": str(sess.get("effortLevel") or sess.get("effort") or "high").lower(),
                "commentsOnly": bool(sess.get("commentsOnly", False)),
                "findingsCount": len(ai_findings),
                "tldr": str(cn.get("tldr") or "")[:240],
                "mtime": mtime,
            }
        )

    if os.path.isdir(WORKSPACES_STATE_DIR):
        for entry in os.listdir(WORKSPACES_STATE_DIR):
            _scan_branch_path(os.path.join(WORKSPACES_STATE_DIR, entry, "active_session.json"), "workspace", "Active Workspace")
    if os.path.isdir(HISTORY_STATE_DIR):
        for entry in os.listdir(HISTORY_STATE_DIR):
            _scan_branch_path(os.path.join(HISTORY_STATE_DIR, entry, "session.json"), "history", "Review History")

    if not candidates:
        return {"ok": True, "found": False}

    candidates.sort(key=lambda c: (0 if c.get("headSha") == live_sha else 1, -float(c.get("mtime") or 0.0)))
    best = candidates[0]
    cached_sha = str(best.get("headSha") or "")
    is_up_to_date = bool(cached_sha and cached_sha == live_sha)

    # If on checked-out branch, check if working-tree files changed compared to the cached snapshot
    if is_up_to_date and cur_b == branch_name:
        head_snap = str((best["session"].get("headSnapshotRoot") or ""))
        if head_snap and os.path.isdir(head_snap):
            for f_entry in best["session"].get("files") or []:
                rel_p = str(f_entry.get("path") or "").strip()
                if not rel_p:
                    continue
                live_f = os.path.join(r_dir, rel_p)
                snap_f = os.path.join(head_snap, rel_p)
                if os.path.isfile(live_f) != os.path.isfile(snap_f):
                    is_up_to_date = False
                    break
                if os.path.isfile(live_f) and os.path.isfile(snap_f):
                    try:
                        if open(live_f, "rb").read() != open(snap_f, "rb").read():
                            is_up_to_date = False
                            break
                    except Exception:
                        pass

    return {
        "ok": True,
        "found": True,
        "isLocalBranch": True,
        "owner": "local",
        "repo": repo_name,
        "branch": branch_name,
        "number": 0,
        "title": best.get("title") or f"{repo_name}@{branch_name}",
        "itemId": str(best["session"].get("sessionId") or f"local-{repo_name}-{branch_name}"),
        "source": best.get("source"),
        "sourceLabel": best.get("sourceLabel"),
        "sessionPath": best.get("sessionPath"),
        "cachedHeadSha": cached_sha,
        "liveHeadSha": live_sha if is_up_to_date else (live_sha if cached_sha != live_sha else f"{live_sha[:7]}+wt"),
        "isUpToDate": is_up_to_date,
        "effort": best.get("effort") or "high",
        "commentsOnly": bool(best.get("commentsOnly", False)),
        "findingsCount": int(best.get("findingsCount") or 0),
        "tldr": best.get("tldr") or "",
    }


def find_existing_completed_review(
    pr_arg: str,
    repo_dir: Optional[str] = None,
    check_live_head: bool = True,
) -> Dict[str, Any]:
    """Checks whether `pr_arg` (GitHub PR or local branch) already has a completed review in Inbox, Workspace, or History."""
    if not pr_arg:
        return {"ok": True, "found": False}
    if not is_github_pr_arg(pr_arg):
        return find_existing_completed_branch_review(pr_arg, repo_dir=repo_dir)
    try:
        owner, repo, pr_num = infer_owner_repo(pr_arg.strip(), repo_dir or os.getcwd())
    except Exception:
        return {"ok": True, "found": False}

    candidates = _scan_completed_sessions_for_pr(owner, repo, pr_num, include_inbox=True)
    if not candidates:
        return {"ok": True, "found": False, "owner": owner, "repo": repo, "number": pr_num}

    live_head_sha = ""
    if check_live_head:
        token = get_github_token()
        if token:
            try:
                pr_obj = _gh_api_get(f"/repos/{owner}/{repo}/pulls/{pr_num}", token, timeout=5.0)
                live_head_sha = str(((pr_obj or {}).get("head") or {}).get("sha") or "")
            except Exception:
                live_head_sha = ""
        if not live_head_sha:
            st = load_inbox_state()
            for it in (st.get("items") or {}).values():
                if (
                    str(it.get("owner") or "").lower() == owner.lower()
                    and str(it.get("repo") or "").lower() == repo.lower()
                    and int(it.get("number") or 0) == pr_num
                ):
                    live_head_sha = str(it.get("headSha") or "")
                    break

    source_prio = {"inbox": 0, "workspace": 1, "history": 2}

    def _sort_key(c: Dict[str, Any]) -> Tuple[int, int, float]:
        matches_live = 0 if (live_head_sha and c.get("headSha") == live_head_sha) else (0 if not live_head_sha else 1)
        return (matches_live, source_prio.get(str(c.get("source")), 9), -float(c.get("mtime") or 0.0))

    candidates.sort(key=_sort_key)
    best = candidates[0]
    cached_sha = str(best.get("headSha") or "")
    is_up_to_date = bool(not live_head_sha or (cached_sha and cached_sha == live_head_sha))

    return {
        "ok": True,
        "found": True,
        "owner": owner,
        "repo": repo,
        "number": pr_num,
        "title": best.get("title") or f"{owner}/{repo}#{pr_num}",
        "prUrl": best.get("prUrl") or f"https://github.com/{owner}/{repo}/pull/{pr_num}",
        "itemId": best.get("itemId") or f"{owner}-{repo}-pr-{pr_num}",
        "source": best.get("source"),
        "sourceLabel": best.get("sourceLabel"),
        "sessionPath": best.get("sessionPath"),
        "cachedHeadSha": cached_sha,
        "liveHeadSha": live_head_sha,
        "isUpToDate": is_up_to_date,
        "effort": best.get("effort") or "high",
        "commentsOnly": bool(best.get("commentsOnly", False)),
        "findingsCount": int(best.get("findingsCount") or 0),
        "blockingCount": int(best.get("blockingCount") or 0),
        "chaptersCount": int(best.get("chaptersCount") or 0),
        "tldr": best.get("tldr") or "",
        "completedAt": best.get("completedAt") or "",
    }


def _extract_session_metrics(session_path: str) -> Dict[str, Any]:
    if not os.path.isfile(session_path):
        return {}
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            sess = json.load(f)
        threads = [t for t in (sess.get("threads") or []) if t.get("status") != "dismissed"]
        ai_findings = [
            t for t in threads if t.get("kind") in ("ai_candidate", "user_staged") and t.get("status") != "fixed"
        ]
        blocking = [t for t in ai_findings if "BLOCK" in str(t.get("severity") or "").upper()]
        uncertain = [t for t in threads if t.get("status") == "uncertain"]
        gh_should_fix = [
            t
            for t in threads
            if t.get("kind") == "github_existing"
            and t.get("status") != "fixed"
            and t.get("triageStatus") in ("recommended_fix", "partially_addressed")
        ]
        cn = sess.get("cliffsNotes") or {}
        sg = sess.get("securityGate")
        return {
            "analysisStatus": sess.get("analysisStatus") or "ready",
            "tldr": str(cn.get("tldr") or "")[:240],
            "findingsCount": len(ai_findings),
            "blockingCount": len(blocking),
            "uncertainCount": len(uncertain),
            "actionableGhCommentsCount": len(gh_should_fix),
            "securityGateStatus": sg.get("status") if isinstance(sg, dict) else "none",
        }
    except Exception:
        return {}


def run_precompute_for_item(
    item_id: str,
    settings: Optional[Dict[str, Any]] = None,
    count_against_daily_budget: bool = True,
) -> Dict[str, Any]:
    """Pre-computes a single PR review into its isolated `~/.gemini/quasar/inbox/items/<id>/` folder."""
    cfg = settings or load_inbox_settings()
    st = load_inbox_state()
    item = (st.get("items") or {}).get(item_id)
    if not item:
        return {"ok": False, "error": f"Inbox item '{item_id}' not found."}

    # Before invoking `agy` in an automatic cycle, check if the user already reviewed this exact headSha manually!
    if count_against_daily_budget and adopt_completed_session_into_inbox(
        item,
        owner=str(item.get("owner") or ""),
        repo=str(item.get("repo") or ""),
        pr_num=int(item.get("number") or 0),
        head_sha=str(item.get("headSha") or ""),
        fingerprint=str(item.get("currentFingerprint") or ""),
        role=str(item.get("role") or "reviewer"),
        expected_review_comments=int(item.get("reviewCommentsCount") or 0),
    ):
        save_inbox_state(st)
        return {"ok": True, "itemId": item_id, "status": "ready", "adoptedFromManualReview": True}

    agy_bin = find_agy_binary()
    if not agy_bin:
        return {"ok": False, "error": "Antigravity CLI (`agy`) not found at ~/.gemini/bin/agy or PATH."}

    item_dir = os.path.join(INBOX_ITEMS_DIR, item_id)
    os.makedirs(item_dir, exist_ok=True)
    session_file = os.path.join(item_dir, "active_session.json")
    prior_backup_path = os.path.join(item_dir, "prior_completed_session.json")
    has_prior_backup = False

    # Preserve any completed earlier-SHA review so we can run an incremental delta update (and restore on error)
    if os.path.isfile(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as sf:
                prev_s = json.load(sf)
            prev_sha = str(((prev_s.get("pr") or {}).get("headSha") or ""))
            if _is_completed_review_session(prev_s) and prev_sha and prev_sha != str(item.get("headSha") or ""):
                shutil.copy2(session_file, prior_backup_path)
                has_prior_backup = True
        except Exception:
            pass

    if not has_prior_backup and cfg.get("incrementalUpdates", True):
        cands = _scan_completed_sessions_for_pr(
            str(item.get("owner") or ""),
            str(item.get("repo") or ""),
            int(item.get("number") or 0),
            include_inbox=False,
        )
        older_cands = [
            c for c in cands if c.get("headSha") and c.get("headSha") != str(item.get("headSha") or "")
        ]
        if older_cands:
            older_cands.sort(key=lambda c: float(c.get("mtime") or 0.0), reverse=True)
            try:
                shutil.copy2(str(older_cands[0]["sessionPath"]), prior_backup_path)
                has_prior_backup = True
            except Exception:
                pass

    item["status"] = "analyzing"
    item["startedAt"] = _now_iso()
    item.pop("lastError", None)
    save_inbox_state(st)

    effort = str(cfg.get("effort") or "high").lower()
    if effort not in ("low", "medium", "high"):
        effort = "high"
    comments_only = bool(cfg.get("commentsOnly", False))
    pr_url = str(item.get("url") or "")
    owner = str(item.get("owner") or "")
    repo = str(item.get("repo") or "")
    repo_dir = auto_detect_repo_dir(owner, repo, None)

    env = dict(os.environ)
    env["QUASAR_SESSION_DIR"] = item_dir

    # Step 1: Deterministic Python context collection + 2.2 Security Gate BEFORE invoking any LLM!
    collect_script = os.path.join(SCRIPT_DIR, "collect_pr_context.py")
    collect_cmd = [
        sys.executable,
        collect_script,
        "--pr",
        pr_url,
        "--effort",
        effort,
        "--comments-only" if comments_only else "--full-guide",
        "--session-dir",
        item_dir,
        "--output-dir",
        item_dir,
    ]
    if has_prior_backup and cfg.get("incrementalUpdates", True):
        collect_cmd.extend(["--incremental-from", prior_backup_path])
    if repo_dir and os.path.isdir(repo_dir):
        collect_cmd.extend(["--repo-dir", repo_dir])

    try:
        c_proc = subprocess.run(collect_cmd, env=env, capture_output=True, text=True, timeout=90)
        if c_proc.returncode != 0:
            raise RuntimeError((c_proc.stderr or c_proc.stdout or "collect_pr_context.py failed").strip())
        ctx_out = json.loads(c_proc.stdout or "{}")
    except Exception as exc:
        if has_prior_backup and os.path.isfile(prior_backup_path):
            shutil.copy2(prior_backup_path, session_file)
        st = load_inbox_state()
        if item_id in st.get("items", {}):
            st["items"][item_id]["status"] = "queued"
            st["items"][item_id]["lastError"] = str(exc)[:300]
            save_inbox_state(st)
        return {"ok": False, "error": str(exc)}

    # Circuit-breaker: if Security Gate flagged `halt_llm_review`, quarantine without invoking `agy`!
    if ctx_out.get("halt_llm_review"):
        st = load_inbox_state()
        if item_id in st.get("items", {}):
            it = st["items"][item_id]
            it["status"] = "quarantined"
            it["analyzedFingerprint"] = it.get("currentFingerprint")
            it["completedAt"] = _now_iso()
            it["unread"] = True
            it.update(_extract_session_metrics(session_file))
            save_inbox_state(st)
        return {"ok": True, "quarantined": True, "itemId": item_id}

    # Step 2: Headless `agy` synthesis strictly isolated to `--session-dir <item_dir>`
    real_state_dir = os.path.realpath(REVIEW_STATE_DIR)
    real_item_dir = os.path.realpath(item_dir)
    real_plugin_dir = os.path.realpath(os.path.expanduser("~/.gemini/config/plugins/quasar"))
    real_agents_dir = os.path.realpath(os.path.expanduser("~/.gemini/config/agents"))
    real_repo = os.path.realpath(repo_dir) if (repo_dir and os.path.isdir(repo_dir)) else ""

    allow_rules = [
        r"command(regex:^python3\s+.*skills/quasar/scripts/.*)",
        "command(git)",
        f"read_file({real_state_dir}/)",
        f"write_file({real_item_dir}/)",
        f"write_file({os.path.join(real_state_dir, 'history')}/)",
        f"read_file({real_plugin_dir}/)",
        f"read_file({real_agents_dir}/)",
    ]
    if real_repo:
        allow_rules.append(f"read_file({real_repo}/)")
    session_settings = json.dumps({"permissions": {"allow": allow_rules}})

    publish_script = os.path.join(SCRIPT_DIR, "publish_review_session.py")
    co_flag = " --comments-only" if comments_only else ""
    is_inc_run = bool(ctx_out.get("is_incremental"))
    inc_note = (
        f"- Incremental Delta Diff (`oldSha -> newSha`): `{item_dir}/delta.diff` (see `incremental_context` in `{item_dir}/pr_context.json` — audit ONLY the delta changes + `priorFindingsToRecheck`, emit `priorFindingUpdates` and `cliffsNotes.deltaSummary`, and emit delta `chapters` covering only `deltaFiles`!)\n"
        if is_inc_run
        else ""
    )
    prompt = (
        f"Background Quasar Inbox {'Incremental ' if is_inc_run else ''}Pre-Review for {pr_url} (`{effort}` effort"
        f"{', comments-only' if comments_only else ''}).\n"
        f"Phase 1 context and snapshots are ALREADY initialized at:\n"
        f"- Context: `{item_dir}/pr_context.json`\n"
        f"- Diff: `{item_dir}/pr.diff`\n"
        f"{inc_note}"
        f"- Isolated Session Dir: `{item_dir}`\n\n"
        f"Using the `quasar` skill on `{effort}` effort:\n"
        f"1. Do NOT re-run `collect_pr_context.py` and do NOT call `ask_question`.\n"
        f"2. Run Phase 2 (`{effort}` effort {'incremental delta ' if is_inc_run else ''}analysis, honoring `review_lenses` and `blindDiff: true` in `{item_dir}/pr_context.json`).\n"
        f"3. Write `review_synthesis.json` to `{item_dir}/review_synthesis.json` and publish STRICTLY to the isolated session dir:\n"
        f'   `python3 "{publish_script}" --input "{item_dir}/review_synthesis.json" --session-dir "{item_dir}"{co_flag}`'
    )

    agy_cmd = [
        agy_bin,
        "--output-format=stream-json",
        "--mode=auto",
    ]
    for d in dict.fromkeys([d for d in (real_repo, real_item_dir, real_state_dir, real_plugin_dir) if d and os.path.isdir(d)]):
        agy_cmd.extend(["--add-dir", d])
    agy_cmd.append(f"--settings={session_settings}")
    agy_cmd.append(f"--print={prompt}")

    log_path = os.path.join(item_dir, "precompute.log")
    run_cwd = real_repo if (real_repo and os.path.isdir(real_repo)) else item_dir
    try:
        with open(log_path, "w", encoding="utf-8") as lf:
            proc = subprocess.run(
                agy_cmd,
                cwd=run_cwd,
                env=env,
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=900,
            )
        metrics = _extract_session_metrics(session_file)
        if metrics.get("analysisStatus") != "ready" and proc.returncode != 0:
            raise RuntimeError(f"agy exited with code {proc.returncode}")
    except Exception as exc:
        if has_prior_backup and os.path.isfile(prior_backup_path):
            shutil.copy2(prior_backup_path, session_file)
        st = load_inbox_state()
        if item_id in st.get("items", {}):
            st["items"][item_id]["status"] = "queued"
            st["items"][item_id]["lastError"] = str(exc)[:300]
            save_inbox_state(st)
        return {"ok": False, "error": str(exc)}

    st = load_inbox_state()
    if count_against_daily_budget:
        st["reviewsRunToday"] = int(st.get("reviewsRunToday") or 0) + 1
    if item_id in st.get("items", {}):
        it = st["items"][item_id]
        it["status"] = "ready"
        it["analyzedFingerprint"] = it.get("currentFingerprint")
        it["analyzedEffort"] = effort
        it["completedAt"] = _now_iso()
        it["unread"] = True
        it.pop("lastError", None)
        it.update(_extract_session_metrics(session_file))
    save_inbox_state(st)
    return {"ok": True, "itemId": item_id, "status": "ready"}


def select_eligible_items_for_cycle(
    settings: Dict[str, Any],
    state: Dict[str, Any],
) -> Tuple[List[str], str]:
    """Selects up to `maxReviewsPerCycle` eligible queued PRs respecting all user safety caps."""
    if settings.get("mode") == "sync_queue_only":
        return [], "sync_queue_only"
    max_per_cycle = int(settings.get("maxReviewsPerCycle") or 0)
    if max_per_cycle <= 0:
        return [], "max_per_cycle_zero"

    max_per_day = int(settings.get("maxReviewsPerDay") or 0)
    run_today = int(state.get("reviewsRunToday") or 0)
    if max_per_day > 0 and run_today >= max_per_day:
        return [], "daily_cap_reached"

    remaining_today = (max_per_day - run_today) if max_per_day > 0 else max_per_cycle
    allowance = min(max_per_cycle, remaining_today)
    if allowance <= 0:
        return [], "daily_cap_reached"

    cutoff_days = int(settings.get("onlyUpdatedWithinDays") or 0)
    now = _now_utc()

    candidates: List[Tuple[int, str, str]] = []
    for iid, item in (state.get("items") or {}).items():
        if not item.get("openInQueue", True):
            continue
        if item.get("dismissed"):
            continue
        if item.get("status") != "queued":
            continue
        if item.get("bucketHint") == "waiting_on_reviewers":
            continue
        if cutoff_days > 0:
            upd_dt = _parse_iso_dt(str(item.get("updatedAt") or ""))
            if upd_dt and (now - upd_dt).total_seconds() > cutoff_days * 86400:
                item["skipReason"] = f"Older than {cutoff_days}d auto-review cutoff"
                continue
        item.pop("skipReason", None)
        # Priority: 0 = updated since last review or author PR with changes requested, 1 = author PR with comments, 2 = review requested
        if item.get("updatedSinceLastReview") or item.get("changesRequested"):
            prio = 0
        elif item.get("role") == "author":
            prio = 1
        else:
            prio = 2
        candidates.append((prio, str(item.get("updatedAt") or ""), iid))

    # Sort highest priority first, then most recently updated first
    candidates.sort(key=lambda t: (t[0], ""), reverse=False)
    candidates.sort(key=lambda t: t[1], reverse=True)
    candidates.sort(key=lambda t: t[0])

    chosen = [iid for _, _, iid in candidates[:allowance]]
    return chosen, "ok"


def run_watch_cycle(force_sync_only: bool = False) -> Dict[str, Any]:
    settings = load_inbox_settings()
    sync_res = sync_github_queue(settings=settings)
    if not sync_res.get("ok"):
        return sync_res

    st = load_inbox_state()
    st["lastCycleAt"] = _now_iso()
    save_inbox_state(st)

    if force_sync_only or settings.get("mode") == "sync_queue_only":
        return {"ok": True, "syncedOnly": True, "discoveredCount": sync_res.get("discoveredCount", 0)}

    chosen_ids, reason = select_eligible_items_for_cycle(settings, st)
    save_inbox_state(st)
    if not chosen_ids:
        return {"ok": True, "processed": [], "reason": reason}

    max_conc = max(1, min(4, int(settings.get("maxConcurrency") or 1)))
    results: List[Dict[str, Any]] = []

    daemon_info = load_daemon_status()
    if daemon_info.get("running"):
        daemon_info["activeItemIds"] = chosen_ids
        save_daemon_status(daemon_info)

    try:
        if max_conc == 1 or len(chosen_ids) == 1:
            for iid in chosen_ids:
                results.append(run_precompute_for_item(iid, settings=settings, count_against_daily_budget=True))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_conc) as pool:
                futs = [
                    pool.submit(run_precompute_for_item, iid, settings, True)
                    for iid in chosen_ids
                ]
                for fut in concurrent.futures.as_completed(futs):
                    results.append(fut.result())
    finally:
        daemon_info = load_daemon_status()
        if daemon_info.get("running"):
            daemon_info["activeItemIds"] = []
            save_daemon_status(daemon_info)

    return {"ok": True, "processed": results, "reason": reason}


def activate_existing_session_file(
    src_session_path: str,
    workspace_dir: Optional[str] = None,
    window_id: Optional[str] = None,
    window_pid: Optional[int] = None,
    item_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Swaps any completed session JSON (from Inbox, History, or another Workspace) into the target window's `active_session.json`."""
    if not src_session_path or not os.path.isfile(src_session_path):
        return {"ok": False, "error": f"Completed session file not found at '{src_session_path}'."}

    clean_ws = resolve_workspace_root(workspace_dir)
    prev_env = os.environ.pop("QUASAR_SESSION_DIR", None)
    try:
        ws_state_dir, dst_session_path, dst_md_path = get_session_paths(clean_ws)
    finally:
        if prev_env is not None:
            os.environ["QUASAR_SESSION_DIR"] = prev_env
    os.makedirs(ws_state_dir, exist_ok=True)

    same_file = os.path.realpath(src_session_path) == os.path.realpath(dst_session_path)

    if not same_file and os.path.isfile(dst_session_path):
        try:
            with open(dst_session_path, "r", encoding="utf-8") as old_f:
                old_sess = json.load(old_f)
            old_md = None
            if os.path.isfile(dst_md_path):
                with open(dst_md_path, "r", encoding="utf-8") as old_mf:
                    old_md = old_mf.read()
            archive_review_session(old_sess, old_md)
        except Exception:
            pass

    with open(src_session_path, "r", encoding="utf-8") as sf:
        sess = json.load(sf)

    # Self-heal snapshot files if the snapshots folder was ever pruned
    head_snap = str(sess.get("headSnapshotRoot") or "")
    pr_meta = sess.get("pr") or {}
    if (
        (not head_snap or not os.path.isdir(head_snap))
        and sess.get("files")
        and pr_meta.get("owner")
        and pr_meta.get("owner") != "local"
    ):
        try:
            r_dir = auto_detect_repo_dir(str(pr_meta.get("owner")), str(pr_meta.get("repo")), clean_ws)
            b_root, h_root = materialize_snapshots(
                session_id=str(sess.get("sessionId") or f"{pr_meta.get('owner')}-{pr_meta.get('repo')}-pr-{pr_meta.get('number')}"),
                owner=str(pr_meta.get("owner")),
                repo=str(pr_meta.get("repo")),
                base_sha=str(pr_meta.get("baseSha") or ""),
                head_sha=str(pr_meta.get("headSha") or ""),
                files_list=sess["files"],
                repo_dir=r_dir,
            )
            sess["baseSnapshotRoot"] = b_root
            sess["headSnapshotRoot"] = h_root
        except Exception:
            pass

    sess["workspaceDir"] = clean_ws
    sess["stateDir"] = ws_state_dir
    eff_wid = window_id or (os.environ.get("QUASAR_WINDOW_ID") or "").strip()
    eff_pid_raw = window_pid or (os.environ.get("QUASAR_WINDOW_PID") or "").strip()
    if eff_wid:
        sess["windowId"] = str(eff_wid)
    else:
        sess.pop("windowId", None)
    if eff_pid_raw and str(eff_pid_raw).isdigit():
        sess["windowPid"] = int(eff_pid_raw)
    else:
        sess.pop("windowPid", None)

    _atomic_write_json(dst_session_path, sess)
    src_dir = os.path.dirname(os.path.abspath(src_session_path))
    if not same_file:
        for extra_name in ("cliffs_notes.md", "pr_context.json", "pr.diff", "quarantined_context.json"):
            src_extra = os.path.join(src_dir, extra_name)
            if os.path.isfile(src_extra):
                shutil.copy2(src_extra, os.path.join(ws_state_dir, extra_name))
    if not os.path.isfile(dst_md_path):
        try:
            with open(dst_md_path, "w", encoding="utf-8") as mf:
                mf.write(render_cliffs_notes_markdown(sess))
        except Exception:
            pass

    # Clear unread flag on any matching Inbox item
    if os.path.isfile(INBOX_STATE_PATH):
        st = load_inbox_state()
        changed = False
        items = st.get("items") or {}
        if item_id and item_id in items:
            items[item_id]["unread"] = False
            items[item_id]["lastOpenedAt"] = _now_iso()
            changed = True
        else:
            for _, it in items.items():
                if _session_matches_pr(
                    sess,
                    str(it.get("owner") or ""),
                    str(it.get("repo") or ""),
                    int(it.get("number") or 0),
                ):
                    it["unread"] = False
                    it["lastOpenedAt"] = _now_iso()
                    changed = True
        if changed:
            save_inbox_state(st)

    return {
        "ok": True,
        "instant": True,
        "itemId": item_id or sess.get("sessionId"),
        "sessionId": sess.get("sessionId"),
        "activeSessionPath": dst_session_path,
        "prUrl": pr_meta.get("url"),
    }


def check_session_head_freshness(
    session_dict: Optional[Dict[str, Any]],
    allow_network: bool = True,
    ttl_seconds: float = 90.0,
) -> Dict[str, Any]:
    """Checks whether an active review session's `pr.headSha` has been superseded by newer commits on GitHub.
    Uses `inbox/state.json` first and a 90s TTL cache (`inbox/head_cache.json`) so polling never spams GitHub.
    """
    if not isinstance(session_dict, dict):
        return {"ok": True, "isStaleHead": False}
    if str(session_dict.get("analysisStatus") or "").lower() == "analyzing":
        return {"ok": True, "isStaleHead": False}
    pr = session_dict.get("pr") or {}
    owner = str(pr.get("owner") or "").strip()
    repo = str(pr.get("repo") or "").strip()
    reviewed_sha = str(pr.get("headSha") or "").strip()
    try:
        pr_num = int(pr.get("number") or 0)
    except Exception:
        pr_num = 0
    if not owner or owner == "local" or not repo or pr_num <= 0 or not reviewed_sha:
        return {"ok": True, "isStaleHead": False}

    latest_sha = ""
    if os.path.isfile(INBOX_STATE_PATH):
        st = load_inbox_state()
        for it in (st.get("items") or {}).values():
            if (
                str(it.get("owner") or "").lower() == owner.lower()
                and str(it.get("repo") or "").lower() == repo.lower()
                and int(it.get("number") or 0) == pr_num
            ):
                latest_sha = str(it.get("headSha") or "")
                break

    cache_path = os.path.join(INBOX_DIR, "head_cache.json")
    cache_key = f"{owner.lower()}/{repo.lower()}#{pr_num}"
    now_ts = time.time()
    cache_data: Dict[str, Any] = {}
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as cf:
                cache_data = json.load(cf) or {}
        except Exception:
            cache_data = {}
    entry = cache_data.get(cache_key) if isinstance(cache_data, dict) else None
    if isinstance(entry, dict) and (now_ts - float(entry.get("checkedAt") or 0.0)) < ttl_seconds:
        if entry.get("headSha"):
            latest_sha = str(entry["headSha"])
    elif allow_network:
        token = get_github_token()
        if token:
            try:
                pr_obj = _gh_api_get(f"/repos/{owner}/{repo}/pulls/{pr_num}", token, timeout=3.5)
                fetched_sha = str(((pr_obj or {}).get("head") or {}).get("sha") or "")
                if fetched_sha:
                    latest_sha = fetched_sha
                    cache_data[cache_key] = {"headSha": fetched_sha, "checkedAt": now_ts}
                    _atomic_write_json(cache_path, cache_data)
            except Exception:
                pass

    is_stale = bool(latest_sha and reviewed_sha and latest_sha != reviewed_sha)
    return {
        "ok": True,
        "isStaleHead": is_stale,
        "reviewedHeadSha": reviewed_sha,
        "latestHeadSha": latest_sha or reviewed_sha,
        "prUrl": pr.get("url") or f"https://github.com/{owner}/{repo}/pull/{pr_num}",
        "owner": owner,
        "repo": repo,
        "number": pr_num,
    }


def activate_inbox_item(
    item_id: str,
    workspace_dir: Optional[str] = None,
    window_id: Optional[str] = None,
    window_pid: Optional[int] = None,
    allow_stale: bool = False,
) -> Dict[str, Any]:
    """Swaps a pre-computed Inbox session into the target window's `active_session.json` in ~0ms."""
    st = load_inbox_state()
    item = (st.get("items") or {}).get(item_id)
    if not item:
        return {"ok": False, "error": f"Inbox item '{item_id}' not found."}

    item_dir = str(item.get("sessionDir") or os.path.join(INBOX_ITEMS_DIR, item_id))
    src_session_path = os.path.join(item_dir, "active_session.json")
    if not os.path.isfile(src_session_path):
        return {
            "ok": True,
            "instant": False,
            "needsLiveReview": True,
            "wasDeleted": bool(item.get("status") == "deleted"),
            "itemId": item_id,
            "prUrl": item.get("url"),
            "effort": load_inbox_settings().get("effort", "high"),
        }

    if not allow_stale:
        try:
            with open(src_session_path, "r", encoding="utf-8") as sf:
                staged_sess = json.load(sf)
            cached_sha = str(((staged_sess.get("pr") or {}).get("headSha") or ""))
            live_sha = str(item.get("headSha") or "")
            if cached_sha and live_sha and cached_sha != live_sha:
                return {
                    "ok": True,
                    "instant": False,
                    "staleSessionAvailable": True,
                    "cachedHeadSha": cached_sha,
                    "liveHeadSha": live_sha,
                    "itemId": item_id,
                    "sessionPath": src_session_path,
                    "prUrl": item.get("url"),
                    "title": item.get("title") or "",
                    "effort": load_inbox_settings().get("effort", "high"),
                }
        except Exception:
            pass

    return activate_existing_session_file(
        src_session_path=src_session_path,
        workspace_dir=workspace_dir,
        window_id=window_id,
        window_pid=window_pid,
        item_id=item_id,
    )


def build_inbox_payload() -> Dict[str, Any]:
    settings = load_inbox_settings()
    state = load_inbox_state()
    daemon = load_daemon_status()

    items_list: List[Dict[str, Any]] = []
    for _, raw_item in (state.get("items") or {}).items():
        if not raw_item.get("openInQueue", True) and raw_item.get("status") != "ready":
            continue
        if raw_item.get("dismissed"):
            continue
        it = dict(raw_item)
        status = str(it.get("status") or "queued")
        role = str(it.get("role") or "reviewer")
        if status == "quarantined":
            group = "quarantined"
        elif status == "analyzing":
            group = "in_progress"
        elif status == "ready" and role == "author":
            group = "author_action_needed"
        elif status == "ready":
            group = "ready_to_review"
        elif status == "deleted":
            group = "deleted"
        elif status in ("waiting_on_author", "waiting_on_reviewers"):
            group = "waiting"
        else:
            group = "queued"
        it["inboxGroup"] = group
        items_list.append(it)

    group_order = {
        "in_progress": 0,
        "ready_to_review": 1,
        "author_action_needed": 2,
        "quarantined": 3,
        "queued": 4,
        "waiting": 5,
        "deleted": 6,
    }
    items_list.sort(key=lambda x: str(x.get("updatedAt") or ""), reverse=True)
    items_list.sort(key=lambda x: group_order.get(str(x.get("inboxGroup")), 9))

    ready_count = sum(
        1 for i in items_list if i.get("inboxGroup") in ("ready_to_review", "author_action_needed")
    )
    unread_ready_count = sum(
        1
        for i in items_list
        if i.get("inboxGroup") in ("ready_to_review", "author_action_needed") and i.get("unread")
    )
    analyzing_count = sum(1 for i in items_list if i.get("inboxGroup") == "in_progress")
    queued_count = sum(1 for i in items_list if i.get("inboxGroup") == "queued")
    deleted_count = sum(1 for i in items_list if i.get("inboxGroup") == "deleted")

    max_day = int(settings.get("maxReviewsPerDay") or 0)
    run_today = int(state.get("reviewsRunToday") or 0)

    return {
        "ok": True,
        "settings": settings,
        "daemon": daemon,
        "githubLogin": state.get("githubLogin") or "",
        "lastSyncedAt": state.get("lastSyncedAt"),
        "lastCycleAt": state.get("lastCycleAt"),
        "lastSyncError": state.get("lastSyncError") or "",
        "budget": {
            "date": state.get("budgetDate"),
            "reviewsRunToday": run_today,
            "maxReviewsPerDay": max_day,
            "dailyCapReached": bool(max_day > 0 and run_today >= max_day),
        },
        "counts": {
            "total": len(items_list),
            "ready": ready_count,
            "unreadReady": unread_ready_count,
            "analyzing": analyzing_count,
            "queued": queued_count,
            "deleted": deleted_count,
        },
        "items": items_list,
    }


def start_daemon_background() -> Dict[str, Any]:
    cur = load_daemon_status()
    if cur.get("running") and cur.get("pid"):
        return {"ok": True, "alreadyRunning": True, "pid": cur["pid"]}

    os.makedirs(INBOX_DIR, exist_ok=True)
    log_f = open(INBOX_LOG_PATH, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--daemon-loop"],
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    save_daemon_status(
        {
            "running": True,
            "pid": proc.pid,
            "startedAt": _now_iso(),
            "activeItemIds": [],
        }
    )
    return {"ok": True, "started": True, "pid": proc.pid, "logPath": INBOX_LOG_PATH}


def stop_daemon_background() -> Dict[str, Any]:
    cur = load_daemon_status()
    pid = cur.get("pid")
    if pid and is_pid_alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
    save_daemon_status({"running": False, "pid": None, "stoppedAt": _now_iso(), "activeItemIds": []})
    return {"ok": True, "stopped": True}


def run_daemon_loop() -> None:
    my_pid = os.getpid()
    save_daemon_status({"running": True, "pid": my_pid, "startedAt": _now_iso(), "activeItemIds": []})

    def _handle_sigterm(_signum: int, _frame: Any) -> None:
        save_daemon_status({"running": False, "pid": None, "stoppedAt": _now_iso(), "activeItemIds": []})
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    while True:
        # Exit if another daemon superseded our PID or user disabled `enabled`
        d_info = load_daemon_status()
        if d_info.get("pid") and int(d_info["pid"]) != my_pid:
            sys.exit(0)
        settings = load_inbox_settings()
        if not settings.get("enabled"):
            save_daemon_status({"running": False, "pid": None, "stoppedAt": _now_iso(), "activeItemIds": []})
            sys.exit(0)

        try:
            run_watch_cycle(force_sync_only=False)
        except Exception as exc:
            d_err = load_daemon_status()
            d_err["lastError"] = str(exc)[:300]
            save_daemon_status(d_err)

        interval_sec = max(120, int(load_inbox_settings().get("pollIntervalMinutes") or 15) * 60)
        next_dt = _now_utc() + datetime.timedelta(seconds=interval_sec)
        d_cur = load_daemon_status()
        d_cur["running"] = True
        d_cur["pid"] = my_pid
        d_cur["lastCycleAt"] = _now_iso()
        d_cur["nextCycleAt"] = next_dt.isoformat()
        save_daemon_status(d_cur)

        slept = 0
        while slept < interval_sec:
            time.sleep(5)
            slept += 5
            cur_cfg = load_inbox_settings()
            if not cur_cfg.get("enabled"):
                save_daemon_status({"running": False, "pid": None, "stoppedAt": _now_iso(), "activeItemIds": []})
                sys.exit(0)
            # Dynamically adjust if user shortened pollIntervalMinutes while sleeping
            new_interval = max(120, int(cur_cfg.get("pollIntervalMinutes") or 15) * 60)
            if slept >= new_interval:
                break


def _dir_size_bytes(path: str) -> int:
    if not path or not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except Exception:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except Exception:
                pass
    return total


def _canonical_review_id(sess: Dict[str, Any], fallback_id: str = "") -> str:
    raw_id = str(sess.get("sessionId") or "").strip()
    if not raw_id:
        pr = sess.get("pr") or {}
        if pr.get("number") and str(pr.get("owner") or "") != "local":
            raw_id = f"{pr.get('owner', 'gh')}-{pr.get('repo', 'repo')}-pr-{pr.get('number')}"
        elif pr.get("headRefName"):
            raw_id = f"local-{pr.get('repo', 'repo')}-{pr.get('headRefName')}"
        else:
            raw_id = fallback_id
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_id).strip("-")


def list_stored_reviews() -> List[Dict[str, Any]]:
    """Lists all stored reviews across History, Inbox staging, and Active Workspaces."""
    records: Dict[str, Dict[str, Any]] = {}
    snaps_root = os.path.join(REVIEW_STATE_DIR, "snapshots")
    now_ts = time.time()

    def _merge_sess(path: str, kind: str, folder_id: str = "") -> None:
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                sess = json.load(f)
        except Exception:
            return
        if not isinstance(sess, dict):
            return
        rid = _canonical_review_id(sess, folder_id)
        if not rid:
            return
        pr = sess.get("pr") or {}
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0.0
        rec = records.get(rid)
        if rec is None:
            title = (
                f"PR #{pr['number']}: {pr.get('title', '')}"
                if pr.get("number")
                else (pr.get("title") or f"Branch: {pr.get('headRefName', rid)}")
            )
            rec = {
                "id": rid,
                "sessionId": rid,
                "title": title,
                "repo": str(pr.get("repo") or ""),
                "owner": str(pr.get("owner") or ""),
                "number": int(pr.get("number") or 0) if str(pr.get("number") or "").isdigit() else 0,
                "updatedAt": str(sess.get("updatedAt") or ""),
                "mtime": mtime,
                "inHistory": False,
                "inInbox": False,
                "inActiveWorkspace": False,
                "historyDirs": [],
                "inboxDirs": [],
                "workspaceDirs": [],
            }
            records[rid] = rec
        else:
            if mtime > float(rec.get("mtime") or 0.0):
                rec["mtime"] = mtime
                if sess.get("updatedAt"):
                    rec["updatedAt"] = str(sess["updatedAt"])
        parent_dir = os.path.dirname(os.path.abspath(path))
        if kind == "history":
            rec["inHistory"] = True
            if parent_dir not in rec["historyDirs"]:
                rec["historyDirs"].append(parent_dir)
        elif kind == "inbox":
            rec["inInbox"] = True
            if parent_dir not in rec["inboxDirs"]:
                rec["inboxDirs"].append(parent_dir)
        elif kind == "workspace":
            rec["inActiveWorkspace"] = True
            if parent_dir not in rec["workspaceDirs"]:
                rec["workspaceDirs"].append(parent_dir)

    if os.path.isdir(HISTORY_STATE_DIR):
        for entry in os.listdir(HISTORY_STATE_DIR):
            _merge_sess(os.path.join(HISTORY_STATE_DIR, entry, "session.json"), "history", entry)
    if os.path.isdir(INBOX_ITEMS_DIR):
        for entry in os.listdir(INBOX_ITEMS_DIR):
            _merge_sess(os.path.join(INBOX_ITEMS_DIR, entry, "active_session.json"), "inbox", entry)
    if os.path.isdir(WORKSPACES_STATE_DIR):
        for entry in os.listdir(WORKSPACES_STATE_DIR):
            _merge_sess(os.path.join(WORKSPACES_STATE_DIR, entry, "active_session.json"), "workspace", entry)

    out: List[Dict[str, Any]] = []
    for rid, rec in records.items():
        disk_bytes = 0
        for d in rec["historyDirs"] + rec["inboxDirs"]:
            disk_bytes += _dir_size_bytes(d)
        if os.path.isdir(snaps_root):
            for sname in os.listdir(snaps_root):
                if sname == rid or sname.startswith(f"{rid}-"):
                    disk_bytes += _dir_size_bytes(os.path.join(snaps_root, sname))
        rec["diskBytes"] = disk_bytes
        rec["ageDays"] = round(max(0.0, (now_ts - float(rec.get("mtime") or now_ts)) / 86400.0), 1)
        out.append(rec)

    out.sort(key=lambda r: float(r.get("mtime") or 0.0), reverse=True)
    return out


def delete_stored_review(
    review_id: str,
    include_active_workspace: bool = True,
    repopulate_as_deleted_in_inbox: bool = True,
) -> Dict[str, Any]:
    """Permanently deletes a stored review across `history/`, `inbox/items/`, `snapshots/`,
    and (when `include_active_workspace=True`) any active workspace holding that session.
    Open GitHub PRs remain visible in the Auto-Review Inbox under `deleted` (`🗑️ Deleted Reviews`)
    so the user can re-add them to the queue or re-review them in 1 click without auto-burning tokens.
    """
    clean_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", (review_id or "").strip()).strip("-")
    if not clean_id or "/" in clean_id or ".." in clean_id:
        return {"ok": False, "error": f"Invalid review ID: '{review_id}'"}

    freed_bytes = 0
    removed_paths: List[str] = []
    captured_pr_meta: Optional[Dict[str, Any]] = None

    def _capture_pr_from_file(json_path: str) -> None:
        nonlocal captured_pr_meta
        if captured_pr_meta is not None or not os.path.isfile(json_path):
            return
        try:
            s_obj = json.load(open(json_path, "r", encoding="utf-8"))
            pr = s_obj.get("pr") if isinstance(s_obj, dict) else None
            if (
                isinstance(pr, dict)
                and pr.get("owner")
                and str(pr.get("owner")) != "local"
                and pr.get("repo")
                and int(pr.get("number") or 0) > 0
            ):
                captured_pr_meta = dict(pr)
        except Exception:
            pass

    _capture_pr_from_file(os.path.join(HISTORY_STATE_DIR, clean_id, "session.json"))
    _capture_pr_from_file(os.path.join(INBOX_ITEMS_DIR, clean_id, "active_session.json"))

    def _rm_dir(d_path: str) -> None:
        nonlocal freed_bytes
        if os.path.isdir(d_path):
            freed_bytes += _dir_size_bytes(d_path)
            shutil.rmtree(d_path, ignore_errors=True)
            removed_paths.append(d_path)

    # 1. History directories matching clean_id (either folder name or session.json sessionId)
    if os.path.isdir(HISTORY_STATE_DIR):
        _rm_dir(os.path.join(HISTORY_STATE_DIR, clean_id))
        for entry in list(os.listdir(HISTORY_STATE_DIR)):
            cand_dir = os.path.join(HISTORY_STATE_DIR, entry)
            cand_json = os.path.join(cand_dir, "session.json")
            if os.path.isfile(cand_json):
                try:
                    s_obj = json.load(open(cand_json, "r", encoding="utf-8"))
                    if _canonical_review_id(s_obj, entry) == clean_id:
                        _capture_pr_from_file(cand_json)
                        _rm_dir(cand_dir)
                except Exception:
                    pass

    # 2. Active workspaces holding this session (capture PR meta before deleting)
    if include_active_workspace and os.path.isdir(WORKSPACES_STATE_DIR):
        for entry in list(os.listdir(WORKSPACES_STATE_DIR)):
            ws_dir = os.path.join(WORKSPACES_STATE_DIR, entry)
            ws_sess = os.path.join(ws_dir, "active_session.json")
            if not os.path.isfile(ws_sess):
                continue
            try:
                s_obj = json.load(open(ws_sess, "r", encoding="utf-8"))
            except Exception:
                continue
            if _canonical_review_id(s_obj) == clean_id:
                _capture_pr_from_file(ws_sess)
                for fn in (
                    "active_session.json",
                    "cliffs_notes.md",
                    "pr_context.json",
                    "pr.diff",
                    "delta.diff",
                    "incremental_base.json",
                    "prior_session_for_delta.json",
                    "quarantined_context.json",
                    "quasar_review.html",
                ):
                    fp = os.path.join(ws_dir, fn)
                    if os.path.isfile(fp):
                        freed_bytes += _dir_size_bytes(fp)
                        try:
                            os.unlink(fp)
                            removed_paths.append(fp)
                        except Exception:
                            pass

    # 3. Inbox staged item directory + repopulate as `status = "deleted"` in state.json
    _rm_dir(os.path.join(INBOX_ITEMS_DIR, clean_id))
    if repopulate_as_deleted_in_inbox or os.path.isfile(INBOX_STATE_PATH):
        st = load_inbox_state()
        items = st.setdefault("items", {})
        if clean_id in items:
            if repopulate_as_deleted_in_inbox and items[clean_id].get("openInQueue", True):
                it = items[clean_id]
                it["dismissed"] = False
                it["unread"] = False
                it["status"] = "deleted"
                it["deletedAt"] = _now_iso()
                it["deletedAtSha"] = str(it.get("headSha") or "")
                for k in (
                    "analyzedFingerprint",
                    "tldr",
                    "findingsCount",
                    "blockingCount",
                    "uncertainCount",
                    "actionableGhCommentsCount",
                ):
                    it.pop(k, None)
            else:
                items.pop(clean_id, None)
            save_inbox_state(st)
        elif (
            repopulate_as_deleted_in_inbox
            and captured_pr_meta is not None
            and str(captured_pr_meta.get("state") or "open").lower() != "closed"
        ):
            own = str(captured_pr_meta.get("owner") or "")
            rep = str(captured_pr_meta.get("repo") or "")
            num = int(captured_pr_meta.get("number") or 0)
            h_sha = str(captured_pr_meta.get("headSha") or "")
            items[clean_id] = {
                "id": clean_id,
                "owner": own,
                "repo": rep,
                "number": num,
                "title": str(captured_pr_meta.get("title") or f"{own}/{rep}#{num}"),
                "url": str(captured_pr_meta.get("url") or f"https://github.com/{own}/{rep}/pull/{num}"),
                "author": str(captured_pr_meta.get("author") or ""),
                "role": "author" if captured_pr_meta.get("isOwnedByUser") else "reviewer",
                "headSha": h_sha,
                "currentFingerprint": h_sha,
                "additions": int(captured_pr_meta.get("additions") or 0),
                "deletions": int(captured_pr_meta.get("deletions") or 0),
                "changedFilesCount": int(captured_pr_meta.get("changedFilesCount") or 0),
                "updatedAt": _now_iso(),
                "openInQueue": True,
                "dismissed": False,
                "unread": False,
                "status": "deleted",
                "deletedAt": _now_iso(),
                "deletedAtSha": h_sha,
                "sessionDir": os.path.join(INBOX_ITEMS_DIR, clean_id),
            }
            save_inbox_state(st)

    # 4. Snapshots (`snapshots/<clean_id>` and `snapshots/<clean_id>-*`)
    snaps_root = os.path.join(REVIEW_STATE_DIR, "snapshots")
    if os.path.isdir(snaps_root):
        for sname in list(os.listdir(snaps_root)):
            if sname == clean_id or sname.startswith(f"{clean_id}-"):
                _rm_dir(os.path.join(snaps_root, sname))

    return {
        "ok": True,
        "deletedId": clean_id,
        "removedPathsCount": len(removed_paths),
        "freedBytes": freed_bytes,
    }


def requeue_inbox_item(item_id: str) -> Dict[str, Any]:
    """Moves a `deleted` or `dismissed` Inbox PR back into `queued` so the auto-review daemon can review it."""
    st = load_inbox_state()
    iid = (item_id or "").strip()
    if iid in st.get("items", {}):
        it = st["items"][iid]
        it["status"] = "queued"
        it["dismissed"] = False
        it["openInQueue"] = True
        it.pop("deletedAt", None)
        it.pop("deletedAtSha", None)
        it.pop("reviewedHeadSha", None)
        save_inbox_state(st)
    return build_inbox_payload()


def prune_old_reviews(
    older_than_days: float = 30.0,
    delete_all: bool = False,
    keep_active_workspaces: bool = True,
) -> Dict[str, Any]:
    """Deletes stored reviews older than `older_than_days` (or all stored reviews when `delete_all=True`),
    plus any orphaned snapshot folders.
    """
    stored = list_stored_reviews()
    deleted_ids: List[str] = []
    freed_bytes = 0

    for rec in stored:
        if keep_active_workspaces and rec.get("inActiveWorkspace"):
            continue
        if delete_all or float(rec.get("ageDays") or 0.0) >= float(older_than_days):
            res = delete_stored_review(
                rec["id"],
                include_active_workspace=not keep_active_workspaces,
                repopulate_as_deleted_in_inbox=True,
            )
            if res.get("ok"):
                deleted_ids.append(rec["id"])
                freed_bytes += int(res.get("freedBytes") or 0)

    # Also clean up orphaned snapshot directories not referenced by any remaining stored review
    remaining_ids = {r["id"] for r in list_stored_reviews()}
    snaps_root = os.path.join(REVIEW_STATE_DIR, "snapshots")
    if os.path.isdir(snaps_root):
        now_ts = time.time()
        for sname in list(os.listdir(snaps_root)):
            s_path = os.path.join(snaps_root, sname)
            if not os.path.isdir(s_path):
                continue
            belongs = any(sname == rid or sname.startswith(f"{rid}-") for rid in remaining_ids)
            if not belongs:
                try:
                    age_d = (now_ts - os.path.getmtime(s_path)) / 86400.0
                except Exception:
                    age_d = 999.0
                if delete_all or age_d >= float(older_than_days):
                    freed_bytes += _dir_size_bytes(s_path)
                    shutil.rmtree(s_path, ignore_errors=True)

    return {
        "ok": True,
        "deletedCount": len(deleted_ids),
        "deletedIds": deleted_ids,
        "freedBytes": freed_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Quasar Background Auto-Review Daemon & Multi-PR Inbox.")
    parser.add_argument("--get-state", action="store_true", help="Print full Inbox payload JSON")
    parser.add_argument("--configure", action="store_true", help="Update Inbox watcher settings")
    parser.add_argument("--settings-json", default="", help="JSON dict of settings updates")
    parser.add_argument("--enable", action="store_true", help="Enable background auto-review & start daemon")
    parser.add_argument("--disable", action="store_true", help="Disable background auto-review & stop daemon")
    parser.add_argument("--poll-minutes", type=int, default=None, help="Poll interval in minutes (e.g. 15)")
    parser.add_argument("--max-per-cycle", type=int, default=None, help="Max auto-reviews per poll cycle (default 1)")
    parser.add_argument("--max-per-day", type=int, default=None, help="Max auto-reviews per day (0 = unlimited, default 6)")
    parser.add_argument("--max-concurrency", type=int, default=None, help="Max concurrent background reviews (default 1)")
    parser.add_argument("--recency-days", type=int, default=None, help="Only auto-review PRs updated within N days (0 = any)")
    parser.add_argument("--effort", choices=["low", "medium", "high"], default=None, help="Background review effort")
    parser.add_argument("--mode", choices=["auto_precompute", "sync_queue_only"], default=None, help="Watcher mode")
    parser.add_argument("--watched-repos", default=None, help="Comma-separated owner/repo watchlist")
    parser.add_argument("--sync-now", action="store_true", help="Poll GitHub queue now without running LLM reviews (0 tokens)")
    parser.add_argument("--run-cycle", action="store_true", help="Run one sync + quota-guarded pre-review cycle and exit")
    parser.add_argument("--precompute-item", default="", help="Explicitly pre-compute a specific Inbox item ID now")
    parser.add_argument("--check-existing", default="", help="Check if a PR URL/ref already has a completed review in Inbox/Workspace/History")
    parser.add_argument("--repo-dir", default=None, help="Optional repo dir for inferring owner/repo when --check-existing uses #number")
    parser.add_argument("--activate", action="store_true", help="Activate/open an Inbox item into the workspace in 0s")
    parser.add_argument("--allow-stale", action="store_true", help="Allow activating an Inbox item even when its cached session is on an older HEAD SHA")
    parser.add_argument("--activate-session", default="", help="Activate any completed session JSON path into the workspace in 0s")
    parser.add_argument("--check-session-freshness", action="store_true", help="Check if the workspace's active_session.json is behind the PR's latest GitHub HEAD SHA")
    parser.add_argument("--mark-reviewed", action="store_true", help="Mark an Inbox item as reviewed at its current HEAD SHA")
    parser.add_argument("--requeue-item", action="store_true", help="Re-add a deleted/dismissed Inbox PR back into the auto-review queue")
    parser.add_argument("--dismiss-item", action="store_true", help="Dismiss/hide an Inbox item and clean up its staged files")
    parser.add_argument("--list-reviews", action="store_true", help="List all stored reviews across History, Inbox, and Workspaces")
    parser.add_argument("--delete-review", default="", help="Permanently delete a stored review ID across History, Inbox, Snapshots, and Workspaces")
    parser.add_argument("--prune-days", type=float, default=None, help="Delete stored reviews and snapshots older than N days")
    parser.add_argument("--delete-all-reviews", action="store_true", help="Delete all stored reviews and snapshots")
    parser.add_argument("--include-active", action="store_true", help="Also delete reviews currently open in active workspaces when pruning")
    parser.add_argument("--item-id", default="", help="Target Inbox item ID")
    parser.add_argument("--workspace-dir", default=None, help="Target workspace directory for --activate")
    parser.add_argument("--start-daemon", action="store_true", help="Start background watcher daemon")
    parser.add_argument("--stop-daemon", action="store_true", help="Stop background watcher daemon")
    parser.add_argument("--daemon-loop", action="store_true", help="Internal detached daemon loop")
    args = parser.parse_args()

    if args.daemon_loop:
        run_daemon_loop()
        return

    updates: Dict[str, Any] = {}
    if args.settings_json.strip():
        updates.update(json.loads(args.settings_json))
    if args.enable:
        updates["enabled"] = True
    if args.disable:
        updates["enabled"] = False
    if args.poll_minutes is not None:
        updates["pollIntervalMinutes"] = args.poll_minutes
    if args.max_per_cycle is not None:
        updates["maxReviewsPerCycle"] = args.max_per_cycle
    if args.max_per_day is not None:
        updates["maxReviewsPerDay"] = args.max_per_day
    if args.max_concurrency is not None:
        updates["maxConcurrency"] = args.max_concurrency
    if args.recency_days is not None:
        updates["onlyUpdatedWithinDays"] = args.recency_days
    if args.effort is not None:
        updates["effort"] = args.effort
    if args.mode is not None:
        updates["mode"] = args.mode
    if args.watched_repos is not None:
        updates["watchedRepos"] = args.watched_repos

    if args.configure or updates:
        saved = save_inbox_settings(updates)
        daemon_res: Dict[str, Any] = {}
        if saved.get("enabled"):
            daemon_res = start_daemon_background()
        elif "enabled" in updates and not saved.get("enabled"):
            daemon_res = stop_daemon_background()
        payload = build_inbox_payload()
        payload["daemonAction"] = daemon_res
        print(json.dumps(payload, indent=2))
        return

    if args.start_daemon:
        save_inbox_settings({"enabled": True})
        res = start_daemon_background()
        print(json.dumps({**build_inbox_payload(), "daemonAction": res}, indent=2))
        return

    if args.stop_daemon:
        save_inbox_settings({"enabled": False})
        res = stop_daemon_background()
        print(json.dumps({**build_inbox_payload(), "daemonAction": res}, indent=2))
        return

    if args.sync_now:
        res = sync_github_queue()
        out = build_inbox_payload()
        out["ok"] = bool(res.get("ok"))
        if res.get("error"):
            out["error"] = res["error"]
        print(json.dumps(out, indent=2))
        return

    if args.run_cycle:
        res = run_watch_cycle(force_sync_only=False)
        out = build_inbox_payload()
        out["cycleResult"] = res
        print(json.dumps(out, indent=2))
        return

    if args.precompute_item:
        res = run_precompute_for_item(args.precompute_item.strip(), count_against_daily_budget=False)
        out = build_inbox_payload()
        out["precomputeResult"] = res
        if not res.get("ok"):
            out["ok"] = False
            out["error"] = res.get("error")
        print(json.dumps(out, indent=2))
        return

    if args.check_existing:
        res = find_existing_completed_review(args.check_existing.strip(), repo_dir=args.repo_dir)
        print(json.dumps(res, indent=2))
        return

    if args.activate_session:
        res = activate_existing_session_file(
            src_session_path=args.activate_session.strip(),
            workspace_dir=args.workspace_dir,
            item_id=args.item_id.strip() or None,
        )
        print(json.dumps(res, indent=2))
        return

    if args.check_session_freshness:
        _, sess_p, _ = get_session_paths(args.workspace_dir)
        sess_obj = None
        if os.path.isfile(sess_p):
            try:
                with open(sess_p, "r", encoding="utf-8") as sf:
                    sess_obj = json.load(sf)
            except Exception:
                sess_obj = None
        print(json.dumps(check_session_head_freshness(sess_obj, allow_network=True), indent=2))
        return

    if args.activate and args.item_id:
        res = activate_inbox_item(
            args.item_id.strip(),
            workspace_dir=args.workspace_dir,
            allow_stale=bool(args.allow_stale),
        )
        print(json.dumps(res, indent=2))
        return

    if args.mark_reviewed and args.item_id:
        st = load_inbox_state()
        iid = args.item_id.strip()
        if iid in st.get("items", {}):
            it = st["items"][iid]
            it["reviewedHeadSha"] = it.get("headSha")
            it["status"] = "waiting_on_author"
            it["unread"] = False
            save_inbox_state(st)
        print(json.dumps(build_inbox_payload(), indent=2))
        return

    if args.list_reviews:
        reviews = list_stored_reviews()
        print(json.dumps({"ok": True, "count": len(reviews), "reviews": reviews}, indent=2))
        return

    if args.delete_review:
        res = delete_stored_review(
            args.delete_review.strip(),
            include_active_workspace=True,
            repopulate_as_deleted_in_inbox=True,
        )
        print(json.dumps(res, indent=2))
        return

    if args.requeue_item and args.item_id:
        print(json.dumps(requeue_inbox_item(args.item_id.strip()), indent=2))
        return

    if args.delete_all_reviews or args.prune_days is not None:
        res = prune_old_reviews(
            older_than_days=float(args.prune_days if args.prune_days is not None else 0.0),
            delete_all=bool(args.delete_all_reviews),
            keep_active_workspaces=not bool(args.include_active),
        )
        print(json.dumps(res, indent=2))
        return

    if args.dismiss_item and args.item_id:
        iid = args.item_id.strip()
        shutil.rmtree(os.path.join(INBOX_ITEMS_DIR, iid), ignore_errors=True)
        st = load_inbox_state()
        if iid in st.get("items", {}):
            st["items"][iid]["dismissed"] = True
            st["items"][iid]["unread"] = False
            st["items"][iid].pop("analyzedFingerprint", None)
            save_inbox_state(st)
        print(json.dumps(build_inbox_payload(), indent=2))
        return

    print(json.dumps(build_inbox_payload(), indent=2))


if __name__ == "__main__":
    main()
