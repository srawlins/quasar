#!/usr/bin/env python3
"""Host-agnostic Gerrit Code Review adapter for Quasar.

Provides zero-dependency (Python stdlib only) support for any standard Gerrit 2.16+ / 3.x
instance (e.g., `*-review.googlesource.com`, `review.opendev.org`, Eclipse, LibreOffice,
Android, Chromium, Go, Dart, Fuchsia, or self-hosted enterprise Gerrit servers).

Capabilities:
- Parses PolyGerrit, subpath-mounted (`/r/c/...`), short (`/+/<num>`), and legacy (`/#/c/...`) URLs,
  including explicit patchset numbers and patchset comparison ranges (`/+/12345/1..3`).
- Resolves authentication agnostically from:
    1. `~/.gemini/quasar/gerrit_auth.json` (per-host user/password, token, or cookie)
    2. Environment variables (`GERRIT_HTTP_USER` + `GERRIT_HTTP_PASSWORD`, `GERRIT_AUTH_TOKEN`, `GERRIT_COOKIE`)
    3. Git cookie files (`git config http.cookiefile` / `~/.gitcookies`, including `#HttpOnly_` entries)
    4. `~/.netrc` / `~/.netrc` Basic/Digest credentials
    5. Anonymous public REST access (with automatic fallback if a local cookie is expired on public hosts)
- Normalizes Gerrit changes, patchsets, commit messages, unified diffs, and threaded comments into
  Quasar's exact `(metadata, comments, files_list, diff_text)` contract.
- Materializes base/head file snapshots via local git object DB (when available) or concurrent Gerrit REST calls.
- Publishes reviews either as Gerrit Draft Comments (`PENDING`) or atomic `Set Review` submissions
  (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`).
"""

import base64
import concurrent.futures
import http.cookiejar
import json
import netrc
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

REVIEW_STATE_DIR = os.path.expanduser("~/.gemini/quasar")
GERRIT_AUTH_PATH = os.path.join(REVIEW_STATE_DIR, "gerrit_auth.json")

NON_GERRIT_HOSTS = {
    "github.com",
    "www.github.com",
    "api.github.com",
    "gist.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
}

XSSI_PREFIX_RE = re.compile(r"^\)\]\}'[^\n]*\n?")


def _sanitize_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip()).strip("-")
    return cleaned or "unknown"


def make_gerrit_session_id(host: str, project: str, change_num: int) -> str:
    """Produces a filesystem-safe canonical session/item ID for a Gerrit change."""
    return f"gerrit-{_sanitize_slug(host.lower())}-{_sanitize_slug(project.lower())}-cl-{int(change_num)}"


def is_gerrit_host_hint(host: str) -> bool:
    h = (host or "").strip().lower().split(":", 1)[0]
    if not h or h in NON_GERRIT_HOSTS:
        return False
    return (
        "gerrit" in h
        or "-review." in h
        or h.startswith("review.")
        or ".googlesource.com" in h
    )


def parse_gerrit_url(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parses a Gerrit change URL into structured components, or returns None if not a Gerrit URL.

    Supported URL shapes:
      - `https://host[/prefix]/c/<project>/+/<number>[/<patchset_or_range>][/<file>]`
      - `https://host[/prefix]/+/<number>[/<patchset_or_range>][/<file>]`
      - `https://host[/prefix]/#/c/[<project>/+/]<number>[/<patchset_or_range>]`
      - `https://<gerrit-like-host>[/prefix]/<number>[/<patchset>]`
    """
    if not raw:
        return None
    s = raw.strip()
    if not s.startswith(("http://", "https://")):
        return None

    try:
        parsed = urllib.parse.urlparse(s)
    except Exception:
        return None

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.strip()
    host_only = netloc.lower().split(":", 1)[0]
    if not netloc or host_only in NON_GERRIT_HOSTS or host_only.endswith(".github.com"):
        return None

    path = parsed.path or ""
    fragment = parsed.fragment or ""

    prefix = ""
    project: Optional[str] = None
    change_num: Optional[int] = None
    patchset: Optional[int] = None
    base_patchset: Optional[int] = None

    def _parse_tail_segments(tail: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        segs = [seg for seg in (tail or "").strip("/").split("/") if seg]
        if not segs or not segs[0].isdigit():
            return None, None, None
        c_num = int(segs[0])
        ps: Optional[int] = None
        base_ps: Optional[int] = None
        if len(segs) >= 2:
            ps_seg = segs[1]
            m_range = re.match(r"^(\d+)\.\.(\d+)$", ps_seg)
            if m_range:
                base_ps = int(m_range.group(1))
                ps = int(m_range.group(2))
            elif ps_seg.isdigit():
                ps = int(ps_seg)
        return c_num, ps, base_ps

    # 1. Legacy hash fragment URLs: `/#/c/<project>/+/<num>[/<ps>]` or `/#/c/<num>[/<ps>]`
    if fragment.startswith("/c/") or fragment.startswith("c/"):
        frag_clean = "/" + fragment.lstrip("/")
        prefix = path.rstrip("/")
        if "/+/" in frag_clean:
            left, right = frag_clean.split("/+/", 1)
            m_proj = re.match(r"^/c/(.+)$", left)
            if m_proj:
                project = urllib.parse.unquote(m_proj.group(1).strip("/"))
                change_num, patchset, base_patchset = _parse_tail_segments(right)
        else:
            after_c = frag_clean[len("/c/") :]
            change_num, patchset, base_patchset = _parse_tail_segments(after_c)

    # 2. Standard PolyGerrit URLs containing `/+/`
    if change_num is None and "/+/" in path:
        left, right = path.split("/+/", 1)
        c_num, ps, base_ps = _parse_tail_segments(right)
        if c_num is not None:
            change_num, patchset, base_patchset = c_num, ps, base_ps
            # Check if `left` contains `/c/<project>`
            m_c = re.match(r"^(.*?)/c/(.+)$", left)
            if m_c:
                prefix = m_c.group(1).rstrip("/")
                project = urllib.parse.unquote(m_c.group(2).strip("/"))
            else:
                prefix = left.rstrip("/")

    # 3. Short numeric URL on known Gerrit hostnames (e.g. `https://go-review.googlesource.com/555123`)
    if change_num is None and is_gerrit_host_hint(host_only):
        m_short = re.match(r"^(.*?)/(\d+)(?:/(\d+\.\.\d+|\d+))?/?$", path)
        if m_short:
            cand_prefix = m_short.group(1).rstrip("/")
            # Avoid matching GitHub/GitLab-style `/pull/123` or `/issues/123` or `/merge_requests/123`
            if not cand_prefix.endswith(("/pull", "/pulls", "/issues", "/merge_requests")):
                prefix = cand_prefix
                tail_str = m_short.group(2) + (f"/{m_short.group(3)}" if m_short.group(3) else "")
                change_num, patchset, base_patchset = _parse_tail_segments(tail_str)

    if change_num is None or change_num <= 0:
        return None

    base_url = f"{scheme}://{netloc}{prefix}".rstrip("/")
    if project:
        canonical_url = f"{base_url}/c/{project}/+/{change_num}"
    else:
        canonical_url = f"{base_url}/+/{change_num}"
    if patchset:
        canonical_url_with_ps = f"{canonical_url}/{patchset}"
    else:
        canonical_url_with_ps = canonical_url

    return {
        "provider": "gerrit",
        "scheme": scheme,
        "host": netloc,
        "hostName": host_only,
        "prefix": prefix,
        "baseUrl": base_url,
        "project": project,
        "number": change_num,
        "patchSet": patchset,
        "basePatchSet": base_patchset,
        "canonicalUrl": canonical_url,
        "requestedUrl": canonical_url_with_ps,
    }


def is_gerrit_url(arg: Optional[str]) -> bool:
    return parse_gerrit_url(arg) is not None


def load_stored_gerrit_auth() -> Dict[str, Any]:
    if os.path.isfile(GERRIT_AUTH_PATH):
        try:
            with open(GERRIT_AUTH_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_stored_gerrit_auth(data: Dict[str, Any]) -> None:
    os.makedirs(REVIEW_STATE_DIR, exist_ok=True)
    tmp_path = f"{GERRIT_AUTH_PATH}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, GERRIT_AUTH_PATH)


def _normalize_host_key(host_or_url: str) -> Tuple[str, str]:
    s = (host_or_url or "").strip()
    if s.startswith(("http://", "https://")):
        p = urllib.parse.urlparse(s)
        clean_path = re.sub(r"/(?:a|c|\+)(?:/.*)?$", "", (p.path or "").rstrip("/"))
        base = f"{p.scheme}://{p.netloc}{clean_path}".rstrip("/")
        return p.netloc.lower(), base
    host = s.split("/", 1)[0].lower()
    return host, f"https://{s.rstrip('/')}"


def _find_gitcookie_for_host(host: str) -> Optional[Tuple[str, str]]:
    """Reads Netscape-formatted git cookie files (`http.cookiefile` / `~/.gitcookies`) for `host`.
    Returns `(cookie_header_value, cookie_file_path)` if a valid matching cookie exists.
    """
    host_clean = (host or "").strip().lower().split(":", 1)[0]
    if not host_clean:
        return None

    cookie_paths: List[str] = []
    env_cf = os.environ.get("GIT_COOKIE_PATH") or os.environ.get("GERRIT_COOKIE_FILE")
    if env_cf:
        cookie_paths.append(os.path.expanduser(env_cf.strip()))

    try:
        res = subprocess.run(
            ["git", "config", "--path", "--get", "http.cookiefile"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            cookie_paths.append(os.path.expanduser(res.stdout.strip()))
    except Exception:
        pass

    cookie_paths.append(os.path.expanduser("~/.gitcookies"))

    now_ts = time.time()
    seen_files = set()
    for cpath in cookie_paths:
        real_p = os.path.abspath(cpath)
        if real_p in seen_files or not os.path.isfile(real_p):
            continue
        seen_files.add(real_p)
        matches: List[Tuple[int, str, str]] = []
        try:
            with open(real_p, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    # Handle `#HttpOnly_` prefix used by curl / git-credential-luci / Gerrit
                    if line.startswith("#HttpOnly_"):
                        line = line[len("#HttpOnly_") :]
                    elif line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 7:
                        continue
                    domain, _flag, _cpath, _secure, expires_raw, name, value = parts[:7]
                    domain_l = domain.strip().lower()
                    try:
                        exp = int(expires_raw.strip())
                        if exp > 0 and exp < now_ts:
                            continue
                    except ValueError:
                        pass
                    if domain_l == host_clean:
                        matches.append((len(domain_l) + 100, name.strip(), value.strip()))
                    elif domain_l.startswith(".") and (
                        host_clean == domain_l[1:] or host_clean.endswith(domain_l)
                    ):
                        matches.append((len(domain_l), name.strip(), value.strip()))
                    elif host_clean.endswith("." + domain_l):
                        matches.append((len(domain_l), name.strip(), value.strip()))
        except Exception:
            continue

        if matches:
            matches.sort(key=lambda item: item[0], reverse=True)
            # Keep unique cookie names with highest specificity first
            chosen: Dict[str, str] = {}
            for _prio, cname, cval in matches:
                if cname and cval and cname not in chosen:
                    chosen[cname] = cval
            if chosen:
                header_val = "; ".join(f"{k}={v}" for k, v in chosen.items())
                return header_val, real_p
    return None


def resolve_gerrit_auth(base_url: str) -> Dict[str, Any]:
    """Resolves Gerrit credentials for `base_url` without requiring any specific auth setup.

    Returns a dict with:
      - `authenticated` (bool): whether credentials were found locally
      - `source` (str): 'quasar_gerrit_auth' | 'env' | 'gitcookies' | 'netrc' | 'anonymous'
      - `headers` (dict): HTTP headers to attach
      - `username` / `password` (optional): for Digest fallback if server requests Digest auth
      - `approveScore` (int): Code-Review score to apply on APPROVE (default 1)
    """
    parsed = urllib.parse.urlparse(base_url if "://" in base_url else f"https://{base_url}")
    netloc_l = (parsed.netloc or "").lower()
    host_only = netloc_l.split(":", 1)[0]

    stored = load_stored_gerrit_auth()
    hosts_map = stored.get("hosts") if isinstance(stored.get("hosts"), dict) else {}
    host_cfg = (
        hosts_map.get(base_url.rstrip("/"))
        or hosts_map.get(netloc_l)
        or hosts_map.get(host_only)
    )
    if not isinstance(host_cfg, dict):
        # Check domain suffix matches (e.g. `.googlesource.com`)
        for k, v in hosts_map.items():
            kl = k.strip().lower()
            if isinstance(v, dict) and kl.startswith(".") and host_only.endswith(kl):
                host_cfg = v
                break

    default_approve = int((host_cfg or {}).get("approveScore") or stored.get("defaultApproveScore") or 1)

    # 1. Explicit `~/.gemini/quasar/gerrit_auth.json`
    if isinstance(host_cfg, dict):
        user = str(host_cfg.get("username") or host_cfg.get("user") or "").strip()
        pwd = str(host_cfg.get("password") or host_cfg.get("httpPassword") or "").strip()
        tok = str(host_cfg.get("token") or "").strip()
        cookie = str(host_cfg.get("cookie") or "").strip()
        if user and pwd:
            b64 = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            return {
                "authenticated": True,
                "source": "quasar_gerrit_auth",
                "headers": {"Authorization": f"Basic {b64}"},
                "username": user,
                "password": pwd,
                "approveScore": default_approve,
            }
        if tok:
            scheme_hdr = str(host_cfg.get("authScheme") or "Bearer").strip()
            return {
                "authenticated": True,
                "source": "quasar_gerrit_auth",
                "headers": {"Authorization": f"{scheme_hdr} {tok}"},
                "approveScore": default_approve,
            }
        if cookie:
            return {
                "authenticated": True,
                "source": "quasar_gerrit_auth",
                "headers": {"Cookie": cookie},
                "approveScore": default_approve,
            }

    # 2. Environment variables
    env_user = (os.environ.get("GERRIT_HTTP_USER") or os.environ.get("GERRIT_USER") or "").strip()
    env_pwd = (os.environ.get("GERRIT_HTTP_PASSWORD") or os.environ.get("GERRIT_PASSWORD") or "").strip()
    env_tok = (os.environ.get("GERRIT_AUTH_TOKEN") or os.environ.get("GERRIT_TOKEN") or "").strip()
    env_cookie = (os.environ.get("GERRIT_COOKIE") or "").strip()
    if env_user and env_pwd:
        b64 = base64.b64encode(f"{env_user}:{env_pwd}".encode("utf-8")).decode("ascii")
        return {
            "authenticated": True,
            "source": "env",
            "headers": {"Authorization": f"Basic {b64}"},
            "username": env_user,
            "password": env_pwd,
            "approveScore": default_approve,
        }
    if env_tok:
        return {
            "authenticated": True,
            "source": "env",
            "headers": {"Authorization": f"Bearer {env_tok}"},
            "approveScore": default_approve,
        }
    if env_cookie:
        return {
            "authenticated": True,
            "source": "env",
            "headers": {"Cookie": env_cookie},
            "approveScore": default_approve,
        }

    # 3. Git cookies (`http.cookiefile` / `~/.gitcookies`)
    cookie_hit = _find_gitcookie_for_host(host_only)
    if cookie_hit:
        cookie_hdr, cookie_file = cookie_hit
        return {
            "authenticated": True,
            "source": "gitcookies",
            "cookieFile": cookie_file,
            "headers": {"Cookie": cookie_hdr},
            "approveScore": default_approve,
        }

    # 4. `~/.netrc`
    for netrc_cand in (os.path.expanduser("~/.netrc"), os.path.expanduser("~/_netrc")):
        if os.path.isfile(netrc_cand):
            try:
                nrc = netrc.netrc(netrc_cand)
                auth_tuple = nrc.authenticators(host_only) or nrc.authenticators(netloc_l)
                if auth_tuple and auth_tuple[0] and auth_tuple[2]:
                    n_user, _acct, n_pwd = auth_tuple
                    b64 = base64.b64encode(f"{n_user}:{n_pwd}".encode("utf-8")).decode("ascii")
                    return {
                        "authenticated": True,
                        "source": "netrc",
                        "netrcFile": netrc_cand,
                        "headers": {"Authorization": f"Basic {b64}"},
                        "username": n_user,
                        "password": n_pwd,
                        "approveScore": default_approve,
                    }
            except Exception:
                pass

    return {
        "authenticated": False,
        "source": "anonymous",
        "headers": {},
        "approveScore": default_approve,
    }


def strip_gerrit_xssi(raw_text: str) -> str:
    return XSSI_PREFIX_RE.sub("", raw_text or "", count=1)


def gerrit_api_request(
    base_url: str,
    endpoint: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    expect_json: bool = True,
    require_auth: bool = False,
    timeout: float = 20.0,
) -> Any:
    """Performs an HTTP request against a Gerrit REST API endpoint.

    Automatically prefixes `/a` when credentials exist, supports Basic + Digest auth + Cookies,
    falls back to unprefixed anonymous GET on public Gerrit hosts if a local cookie is stale,
    and strips Gerrit's `)]}'` XSSI prefix on JSON responses.
    """
    clean_base = base_url.rstrip("/")
    ep = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    if ep.startswith("/a/"):
        ep = ep[2:]

    auth = resolve_gerrit_auth(clean_base)
    has_creds = bool(auth.get("authenticated"))
    if require_auth and not has_creds:
        parsed_h = urllib.parse.urlparse(clean_base).netloc or clean_base
        raise RuntimeError(
            f"NO_GERRIT_AUTH: Publishing to Gerrit ({parsed_h}) requires authentication. "
            f"Configure `~/.gitcookies`, `~/.netrc`, or run: "
            f"`python3 post_pending_review.py --set-gerrit-auth {parsed_h} <username> <http-password>`."
        )

    body_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None

    def _send(use_auth: bool, use_digest: bool = False) -> bytes:
        url = f"{clean_base}{'/a' if use_auth else ''}{ep}"
        headers: Dict[str, str] = {
            "User-Agent": "quasar",
            "Accept": "application/json" if expect_json else "*/*",
        }
        if body_bytes is not None:
            headers["Content-Type"] = "application/json; charset=UTF-8"
        if use_auth and not use_digest:
            headers.update(auth.get("headers") or {})

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())
        if use_auth and use_digest and auth.get("username") and auth.get("password"):
            mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            mgr.add_password(None, url, str(auth["username"]), str(auth["password"]))
            opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))
            with opener.open(req, timeout=timeout) as resp:
                return resp.read()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    raw_bytes: bytes
    try:
        raw_bytes = _send(use_auth=has_creds)
    except urllib.error.HTTPError as err:
        www_auth = str(err.headers.get("WWW-Authenticate") or "") if err.headers else ""
        # 1. Retry with HTTP Digest auth if the Gerrit server uses Digest on `/a/`
        if (
            has_creds
            and err.code == 401
            and "digest" in www_auth.lower()
            and auth.get("username")
            and auth.get("password")
        ):
            try:
                raw_bytes = _send(use_auth=True, use_digest=True)
            except urllib.error.HTTPError as dig_err:
                if method.upper() == "GET" and not require_auth and dig_err.code in (401, 403):
                    raw_bytes = _send(use_auth=False)
                else:
                    err_txt = ""
                    try:
                        err_txt = dig_err.read().decode("utf-8", errors="replace").strip()
                    except Exception:
                        pass
                    raise RuntimeError(f"Gerrit HTTP {dig_err.code} on {ep}: {err_txt or dig_err.reason}")
        # 2. If reading a public Gerrit server with an expired/unmatched local cookie, fall back to anonymous GET
        elif has_creds and method.upper() == "GET" and not require_auth and err.code in (401, 403):
            try:
                raw_bytes = _send(use_auth=False)
            except urllib.error.HTTPError as anon_err:
                err_txt = ""
                try:
                    err_txt = anon_err.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
                raise RuntimeError(f"Gerrit HTTP {anon_err.code} on {ep}: {err_txt or anon_err.reason}")
        else:
            err_txt = ""
            try:
                err_txt = err.read().decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            raise RuntimeError(f"Gerrit HTTP {err.code} on {ep}: {err_txt or err.reason}")

    if not expect_json:
        return raw_bytes

    text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    cleaned = strip_gerrit_xssi(text).strip()
    if not cleaned:
        return {}
    return json.loads(cleaned)


def set_gerrit_host_auth(
    host_or_url: str,
    username: str = "",
    password: str = "",
    token: str = "",
    cookie: str = "",
    approve_score: int = 1,
    verify: bool = True,
) -> Dict[str, Any]:
    """Saves Gerrit credentials for a host into `~/.gemini/quasar/gerrit_auth.json` and optionally verifies via `/a/accounts/self`."""
    host_key, base_url = _normalize_host_key(host_or_url)
    stored = load_stored_gerrit_auth()
    hosts = stored.setdefault("hosts", {})
    entry: Dict[str, Any] = {"baseUrl": base_url, "approveScore": int(approve_score or 1)}
    if username and password:
        entry["username"] = username.strip()
        entry["password"] = password.strip()
    elif token:
        entry["token"] = token.strip()
    elif cookie:
        entry["cookie"] = cookie.strip()
    else:
        raise ValueError("Provide username+password, token, or cookie for Gerrit authentication.")

    hosts[host_key] = entry
    save_stored_gerrit_auth(stored)

    account_info: Dict[str, Any] = {}
    if verify:
        try:
            acct = gerrit_api_request(base_url, "/accounts/self", require_auth=True, timeout=10.0)
            if isinstance(acct, dict):
                account_info = {
                    "accountId": acct.get("_account_id"),
                    "username": acct.get("username") or acct.get("name") or username,
                    "name": acct.get("name") or "",
                    "email": acct.get("email") or "",
                }
                entry.update({k: v for k, v in account_info.items() if v is not None})
                hosts[host_key] = entry
                save_stored_gerrit_auth(stored)
        except Exception as exc:
            return {
                "ok": False,
                "host": host_key,
                "baseUrl": base_url,
                "error": str(exc),
            }

    return {
        "ok": True,
        "host": host_key,
        "baseUrl": base_url,
        "account": account_info,
        "authFilePath": GERRIT_AUTH_PATH,
    }


def get_gerrit_auth_status(host_or_url: Optional[str] = None) -> Dict[str, Any]:
    stored = load_stored_gerrit_auth()
    configured_hosts = sorted((stored.get("hosts") or {}).keys()) if isinstance(stored.get("hosts"), dict) else []
    out: Dict[str, Any] = {
        "ok": True,
        "authFilePath": GERRIT_AUTH_PATH,
        "configuredHosts": configured_hosts,
        "hasGitCookiesFile": bool(
            os.path.isfile(os.path.expanduser("~/.gitcookies"))
        ),
    }
    if host_or_url:
        _hk, base_url = _normalize_host_key(host_or_url)
        resolved = resolve_gerrit_auth(base_url)
        out["targetHost"] = {
            "baseUrl": base_url,
            "authenticated": bool(resolved.get("authenticated")),
            "source": resolved.get("source"),
            "approveScore": resolved.get("approveScore", 1),
        }
    return out


def _format_gerrit_account(acct: Optional[Dict[str, Any]]) -> str:
    if not isinstance(acct, dict):
        return "reviewer"
    if acct.get("username"):
        return str(acct["username"]).strip()
    if acct.get("email"):
        return str(acct["email"]).strip().split("@", 1)[0]
    if acct.get("name"):
        return str(acct["name"]).strip()
    if acct.get("_account_id") is not None:
        return f"account-{acct['_account_id']}"
    return "reviewer"


def _split_unified_diff_by_file(diff_text: str) -> Dict[str, str]:
    """Extracts per-file `diff --git ...` patch blocks keyed by new (or old) relative path."""
    patches: Dict[str, str] = {}
    if not diff_text:
        return patches
    blocks = re.split(r"(?m)^(?=diff --git )", diff_text)
    for blk in blocks:
        if not blk.startswith("diff --git "):
            continue
        first_nl = blk.find("\n")
        header = blk[:first_nl] if first_nl != -1 else blk
        # Match `diff --git a/<old> b/<new>`
        m_plus = re.search(r"(?m)^\+\+\+ b/(.+)$", blk)
        m_minus = re.search(r"(?m)^--- a/(.+)$", blk)
        if m_plus and m_plus.group(1).strip() != "/dev/null":
            patches[m_plus.group(1).strip()] = blk
        if m_minus and m_minus.group(1).strip() != "/dev/null":
            old_p = m_minus.group(1).strip()
            patches.setdefault(old_p, blk)
        if not m_plus and not m_minus:
            m_hdr = re.match(r"^diff --git a/(.+?) b/(.+)$", header.strip())
            if m_hdr:
                patches.setdefault(m_hdr.group(2).strip(), blk)
    return patches


def _extract_hunk_around_line(file_patch: str, line_num: int, side: str = "RIGHT") -> str:
    """Extracts a compact diff hunk excerpt around `line_num` from `file_patch` for code-state enrichment."""
    if not file_patch or not line_num:
        return ""
    hunks = re.split(r"(?m)^(?=@@ -\d+)", file_patch)
    for h in hunks:
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", h)
        if not m:
            continue
        old_s = int(m.group(1))
        old_c = int(m.group(2) if m.group(2) is not None else 1)
        new_s = int(m.group(3))
        new_c = int(m.group(4) if m.group(4) is not None else 1)
        if side == "LEFT":
            if old_s - 3 <= line_num <= old_s + max(old_c, 1) + 3:
                return h.strip()[-1200:]
        else:
            if new_s - 3 <= line_num <= new_s + max(new_c, 1) + 3:
                return h.strip()[-1200:]
    return ""


def _decode_gerrit_base64(raw_bytes: bytes) -> bytes:
    if not raw_bytes:
        return b""
    try:
        return base64.b64decode(raw_bytes, validate=False)
    except Exception:
        return raw_bytes


def _change_endpoint_id(project: Optional[str], change_num: int) -> str:
    if project:
        return f"{urllib.parse.quote(project, safe='')}~{int(change_num)}"
    return str(int(change_num))


def fetch_gerrit_change(
    gerrit_url: str,
    parse_first_changed_line_fn: Callable[[str], Tuple[int, int]],
    parse_all_hunks_fn: Callable[[str], List[Dict[str, int]]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Fetches a Gerrit change and returns `(metadata, comments, files_list, diff_text)`
    matching Quasar's exact `fetch_pr_via_rest` return contract.
    """
    spec = parse_gerrit_url(gerrit_url)
    if not spec:
        raise ValueError(f"Invalid Gerrit URL: {gerrit_url}")

    base_url = spec["baseUrl"]
    change_num = int(spec["number"])
    req_project = spec.get("project")
    req_ps = spec.get("patchSet")

    query_opts = (
        "o=ALL_REVISIONS&o=ALL_COMMITS&o=DETAILED_ACCOUNTS&o=DETAILED_LABELS&o=MESSAGES"
    )
    cid = _change_endpoint_id(req_project, change_num)
    try:
        change = gerrit_api_request(base_url, f"/changes/{cid}?{query_opts}")
    except Exception:
        if req_project:
            cid = str(change_num)
            change = gerrit_api_request(base_url, f"/changes/{cid}?{query_opts}")
        else:
            raise

    if not isinstance(change, dict):
        raise RuntimeError(f"Unexpected Gerrit change payload for {gerrit_url}")

    project = str(change.get("project") or req_project or "repo").strip()
    cid = _change_endpoint_id(project, change_num)
    revisions = change.get("revisions") or {}
    if not isinstance(revisions, dict) or not revisions:
        raise RuntimeError(f"Gerrit change #{change_num} has no revisions.")

    rev_entries: List[Tuple[int, str, Dict[str, Any]]] = []
    for sha, r_obj in revisions.items():
        if isinstance(r_obj, dict):
            rev_entries.append((int(r_obj.get("_number") or 0), str(sha), r_obj))
    rev_entries.sort(key=lambda item: item[0])

    latest_ps, latest_sha, latest_rev_obj = rev_entries[-1]
    cur_rev_sha = str(change.get("current_revision") or latest_sha)
    if cur_rev_sha in revisions and not req_ps:
        target_sha = cur_rev_sha
        target_rev = revisions[cur_rev_sha]
        target_ps = int(target_rev.get("_number") or latest_ps)
    elif req_ps:
        matched = next((item for item in rev_entries if item[0] == int(req_ps)), None)
        if matched:
            target_ps, target_sha, target_rev = matched
        else:
            target_ps, target_sha, target_rev = latest_ps, latest_sha, latest_rev_obj
    else:
        target_ps, target_sha, target_rev = latest_ps, latest_sha, latest_rev_obj

    commit_obj = target_rev.get("commit") if isinstance(target_rev, dict) else {}
    if not isinstance(commit_obj, dict):
        commit_obj = {}
    parents = commit_obj.get("parents") or []
    base_sha = ""
    if isinstance(parents, list) and parents and isinstance(parents[0], dict):
        base_sha = str(parents[0].get("commit") or "")

    full_commit_msg = str(commit_obj.get("message") or "").strip()
    subject = str(change.get("subject") or commit_obj.get("subject") or f"Change {change_num}").strip()
    # Extract commit body (everything after the first subject line)
    msg_lines = full_commit_msg.splitlines()
    commit_body = "\n".join(msg_lines[1:]).strip() if len(msg_lines) > 1 else ""

    # Fetch unified diff (`/patch` is base64-encoded git format-patch) and `/files` + `/comments` concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fut_patch = pool.submit(
            gerrit_api_request,
            base_url,
            f"/changes/{cid}/revisions/{target_sha}/patch",
            expect_json=False,
        )
        fut_files = pool.submit(
            gerrit_api_request,
            base_url,
            f"/changes/{cid}/revisions/{target_sha}/files",
        )
        fut_comments = pool.submit(
            gerrit_api_request,
            base_url,
            f"/changes/{cid}/comments",
        )

        raw_patch_b64 = fut_patch.result()
        files_map = fut_files.result()
        comments_map = fut_comments.result()

    decoded_mbox = _decode_gerrit_base64(raw_patch_b64).decode("utf-8", errors="replace")
    diff_idx = decoded_mbox.find("diff --git ")
    diff_text = decoded_mbox[diff_idx:] if diff_idx != -1 else ""
    patches_by_file = _split_unified_diff_by_file(diff_text)

    files_list: List[Dict[str, Any]] = []
    status_code_map = {
        "A": "added",
        "C": "added",
        "D": "removed",
        "R": "modified",
        "M": "modified",
        "W": "modified",
    }
    if isinstance(files_map, dict):
        for fpath, finfo in files_map.items():
            if fpath in ("/COMMIT_MSG", "/MERGE_LIST", "/PATCHSET_LEVEL"):
                continue
            if not isinstance(finfo, dict):
                finfo = {}
            raw_st = str(finfo.get("status") or "M").upper()
            q_status = status_code_map.get(raw_st, "modified")
            file_patch = patches_by_file.get(fpath) or patches_by_file.get(str(finfo.get("old_path") or "")) or ""
            s_line, e_line = parse_first_changed_line_fn(file_patch)
            f_entry: Dict[str, Any] = {
                "path": fpath,
                "status": q_status,
                "added": int(finfo.get("lines_inserted") or 0),
                "deleted": int(finfo.get("lines_deleted") or 0),
                "firstChangedStartLine": s_line,
                "firstChangedEndLine": e_line,
                "hunks": parse_all_hunks_fn(file_patch),
            }
            if finfo.get("old_path"):
                f_entry["previousPath"] = str(finfo["old_path"])
            files_list.append(f_entry)

    # Assemble top-level messages + threaded inline comments
    comments: List[Dict[str, Any]] = []
    auto_tag_prefixes = ("autogenerated:",)
    for msg_obj in (change.get("messages") or [])[-80:]:
        if not isinstance(msg_obj, dict):
            continue
        tag = str(msg_obj.get("tag") or "").lower()
        msg_body = str(msg_obj.get("message") or "").strip()
        if not msg_body:
            continue
        # Skip bare `Uploaded patch set N.` noise when there is no human text beyond the header
        stripped_hdr = re.sub(
            r"^Patch Set \d+:(?:\s*[A-Za-z0-9_-]+[+-]\d+)*\s*(?:\(\d+ comments?\))?\s*",
            "",
            msg_body,
            count=1,
        ).strip()
        if not stripped_hdr or stripped_hdr.startswith("Uploaded patch set "):
            continue
        if any(tag.startswith(p) for p in auto_tag_prefixes) and "bot" in _format_gerrit_account(msg_obj.get("author")).lower():
            continue
        comments.append(
            {
                "id": f"gerrit-msg-{msg_obj.get('id') or len(comments) + 1}",
                "type": "issue_comment",
                "author": _format_gerrit_account(msg_obj.get("author")),
                "created_at": msg_obj.get("date"),
                "body": msg_body[:2000],
            }
        )

    inline_by_raw_id: Dict[str, Dict[str, Any]] = {}
    orphan_replies: List[Tuple[str, Dict[str, Any], Dict[str, Any], str]] = []

    if isinstance(comments_map, dict):
        for fpath, c_list in comments_map.items():
            if not isinstance(c_list, list):
                continue
            # Sort chronologically so parent comments precede replies
            sorted_c = sorted(c_list, key=lambda x: str((x or {}).get("updated") or ""))
            if fpath in ("/COMMIT_MSG", "/MERGE_LIST", "/PATCHSET_LEVEL"):
                label_prefix = "[Commit Message] " if fpath == "/COMMIT_MSG" else ""
                for c_obj in sorted_c:
                    if not isinstance(c_obj, dict):
                        continue
                    c_body = str(c_obj.get("message") or "").strip()
                    if not c_body:
                        continue
                    comments.append(
                        {
                            "id": f"gerrit-top-{c_obj.get('id')}",
                            "type": "issue_comment",
                            "author": _format_gerrit_account(c_obj.get("author")),
                            "created_at": c_obj.get("updated"),
                            "body": f"{label_prefix}{c_body}"[:2000],
                        }
                    )
                continue

            file_patch = patches_by_file.get(fpath) or ""
            for c_obj in sorted_c:
                if not isinstance(c_obj, dict):
                    continue
                raw_id = str(c_obj.get("id") or "")
                if not raw_id:
                    continue
                reply_to = str(c_obj.get("in_reply_to") or "").strip()
                c_author = _format_gerrit_account(c_obj.get("author"))
                c_body = str(c_obj.get("message") or "")[:2000]
                rng = c_obj.get("range") if isinstance(c_obj.get("range"), dict) else {}
                line_no = int(
                    c_obj.get("line")
                    or rng.get("end_line")
                    or rng.get("start_line")
                    or 1
                )
                side = "LEFT" if str(c_obj.get("side") or "REVISION").upper() == "PARENT" else "RIGHT"
                c_commit = str(c_obj.get("commit_id") or "")
                c_ps = int(c_obj.get("patch_set") or 0)
                is_outdated = bool((c_commit and c_commit != target_sha) or (c_ps and c_ps != target_ps))

                if reply_to:
                    reply_entry = {
                        "id": f"gerrit-inline-{raw_id}",
                        "raw_id": raw_id,
                        "in_reply_to_id": reply_to,
                        "author": c_author,
                        "created_at": c_obj.get("updated"),
                        "body": c_body,
                        "unresolved": bool(c_obj.get("unresolved", False)),
                    }
                    parent = inline_by_raw_id.get(reply_to)
                    if parent is not None:
                        parent.setdefault("replies", []).append(reply_entry)
                        parent["unresolved"] = bool(c_obj.get("unresolved", False))
                    else:
                        orphan_replies.append((reply_to, reply_entry, c_obj, fpath))
                else:
                    entry = {
                        "id": f"gerrit-inline-{raw_id}",
                        "raw_id": raw_id,
                        "type": "inline_comment",
                        "author": c_author,
                        "path": fpath,
                        "line": line_no,
                        "raw_line": c_obj.get("line") or rng.get("end_line"),
                        "original_line": line_no,
                        "is_outdated": is_outdated,
                        "unresolved": bool(c_obj.get("unresolved", True)),
                        "commit_id": target_sha,
                        "original_commit_id": c_commit or target_sha,
                        "diff_hunk": _extract_hunk_around_line(file_patch, line_no, side=side),
                        "side": side,
                        "created_at": c_obj.get("updated"),
                        "body": c_body,
                        "replies": [],
                    }
                    inline_by_raw_id[raw_id] = entry
                    comments.append(entry)

    # Resolve multi-hop reply chains (`reply -> reply -> root`)
    parent_lookup: Dict[str, Dict[str, Any]] = dict(inline_by_raw_id)
    for reply_to, reply_entry, c_obj, fpath in orphan_replies:
        # Walk up if reply_to was itself a reply already attached to a root
        target_parent = parent_lookup.get(reply_to)
        if target_parent is not None:
            target_parent.setdefault("replies", []).append(reply_entry)
            target_parent["unresolved"] = bool(reply_entry.get("unresolved", False))
            parent_lookup[str(reply_entry["raw_id"])] = target_parent
        else:
            line_no = int(c_obj.get("line") or 1)
            side = "LEFT" if str(c_obj.get("side") or "REVISION").upper() == "PARENT" else "RIGHT"
            fallback_root = {
                "id": reply_entry["id"],
                "raw_id": reply_entry["raw_id"],
                "in_reply_to_id": reply_to,
                "type": "inline_comment",
                "author": reply_entry["author"],
                "path": fpath,
                "line": line_no,
                "raw_line": c_obj.get("line"),
                "original_line": line_no,
                "is_outdated": bool(int(c_obj.get("patch_set") or 0) != target_ps),
                "unresolved": bool(reply_entry.get("unresolved", False)),
                "commit_id": target_sha,
                "original_commit_id": str(c_obj.get("commit_id") or target_sha),
                "diff_hunk": _extract_hunk_around_line(patches_by_file.get(fpath) or "", line_no, side=side),
                "side": side,
                "created_at": reply_entry["created_at"],
                "body": reply_entry["body"],
                "replies": [],
            }
            parent_lookup[str(reply_entry["raw_id"])] = fallback_root
            comments.append(fallback_root)

    raw_status = str(change.get("status") or "NEW").upper()
    norm_state = "open" if raw_status == "NEW" else ("merged" if raw_status == "MERGED" else "closed")
    canonical_change_url = f"{base_url}/c/{project}/+/{change_num}"
    if req_ps:
        canonical_change_url = f"{canonical_change_url}/{target_ps}"

    additions = sum(int(f.get("added") or 0) for f in files_list) or int(change.get("insertions") or 0)
    deletions = sum(int(f.get("deleted") or 0) for f in files_list) or int(change.get("deletions") or 0)
    ref_spec = str(target_rev.get("ref") or f"refs/changes/{change_num % 100:02d}/{change_num}/{target_ps}")

    # Revision SHA -> patchset map so incremental reviews can fetch old patchset files directly from Gerrit
    revision_patchsets = {str(sha): int(ps_n) for ps_n, sha, _r in rev_entries}

    metadata: Dict[str, Any] = {
        "provider": "gerrit",
        "gerritBaseUrl": base_url,
        "gerritHost": spec["host"],
        "gerritProject": project,
        "gerritChangeId": str(change.get("change_id") or ""),
        "patchSet": target_ps,
        "latestPatchSet": latest_ps,
        "latestHeadSha": latest_sha,
        "revisionPatchSets": revision_patchsets,
        "owner": spec["host"].lower(),
        "repo": project,
        "number": change_num,
        "title": subject,
        "url": canonical_change_url,
        "state": norm_state,
        "author": _format_gerrit_account(change.get("owner")),
        "authorEmail": str((change.get("owner") or {}).get("email") or ""),
        "baseRefName": str(change.get("branch") or "main"),
        "baseSha": base_sha,
        "headRefName": ref_spec,
        "headBranch": ref_spec,
        "headSha": target_sha,
        "additions": additions,
        "deletions": deletions,
        "changedFilesCount": len(files_list),
        "body": commit_body,
    }

    return metadata, comments, files_list, diff_text


def fetch_gerrit_file_content(
    base_url: str,
    project: str,
    change_num: int,
    revision_sha_or_ps: str,
    rel_path: str,
    parent: bool = False,
    base_sha: str = "",
    repo_dir: Optional[str] = None,
) -> Optional[str]:
    """Fetches a single file's UTF-8 content at a Gerrit revision (or its parent base commit)."""
    target_sha = base_sha if parent else revision_sha_or_ps
    if (
        repo_dir
        and target_sha
        and len(target_sha) == 40
        and os.path.isdir(os.path.join(repo_dir, ".git"))
    ):
        try:
            res = subprocess.run(
                ["git", "show", f"{target_sha}:{rel_path}"],
                cwd=repo_dir,
                capture_output=True,
                timeout=4,
            )
            if res.returncode == 0:
                return res.stdout.decode("utf-8", errors="replace")
        except Exception:
            pass

    cid = _change_endpoint_id(project, change_num)
    q_file = urllib.parse.quote(rel_path, safe="")
    rev_q = urllib.parse.quote(str(revision_sha_or_ps), safe="")
    suffix = "?parent=1" if parent else ""
    try:
        raw_b64 = gerrit_api_request(
            base_url,
            f"/changes/{cid}/revisions/{rev_q}/files/{q_file}/content{suffix}",
            expect_json=False,
        )
        return _decode_gerrit_base64(raw_b64).decode("utf-8", errors="replace")
    except Exception:
        if parent and base_sha and project:
            try:
                q_proj = urllib.parse.quote(project, safe="")
                raw_b64 = gerrit_api_request(
                    base_url,
                    f"/projects/{q_proj}/commits/{base_sha}/files/{q_file}/content",
                    expect_json=False,
                )
                return _decode_gerrit_base64(raw_b64).decode("utf-8", errors="replace")
            except Exception:
                return None
        return None


def materialize_gerrit_snapshots(
    session_id: str,
    snapshots_dir: str,
    metadata: Dict[str, Any],
    files_list: List[Dict[str, Any]],
    repo_dir: Optional[str] = None,
    max_files: int = 120,
) -> Tuple[str, str]:
    """Downloads base and head file snapshots for a Gerrit change into `<snapshots_dir>/<session_id>/{base,head}`."""
    import shutil

    head_sha = str(metadata.get("headSha") or metadata.get("patchSet") or "current")
    sha_tag = head_sha[:8] if head_sha and head_sha != "current" else ""
    snap_folder = f"{session_id}-{sha_tag}" if sha_tag else session_id
    snap_root = os.path.join(snapshots_dir, snap_folder)
    base_root = os.path.join(snap_root, "base")
    head_root = os.path.join(snap_root, "head")
    if os.path.exists(snap_root):
        shutil.rmtree(snap_root, ignore_errors=True)
    os.makedirs(base_root, exist_ok=True)
    os.makedirs(head_root, exist_ok=True)

    # Keep at most 3 recent patchset snapshot folders per session so incremental delta reviews work cleanly
    if os.path.isdir(snapshots_dir):
        prefix = f"{session_id}-"
        matching_dirs = [
            os.path.join(snapshots_dir, d)
            for d in os.listdir(snapshots_dir)
            if d.startswith(prefix) and os.path.isdir(os.path.join(snapshots_dir, d))
        ]
        if len(matching_dirs) > 3:
            matching_dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for old_d in matching_dirs[3:]:
                if os.path.abspath(old_d) != os.path.abspath(snap_root):
                    shutil.rmtree(old_d, ignore_errors=True)

    base_url = str(metadata.get("gerritBaseUrl") or "")
    project = str(metadata.get("gerritProject") or metadata.get("repo") or "")
    change_num = int(metadata.get("number") or 0)
    base_sha = str(metadata.get("baseSha") or "")

    target_files = files_list[:max_files]

    def _write_snap(root: str, rel_path: str, content: str) -> None:
        safe_rel = os.path.normpath(rel_path).lstrip(os.sep)
        if safe_rel.startswith(".."):
            return
        full_p = os.path.join(root, safe_rel)
        os.makedirs(os.path.dirname(full_p), exist_ok=True)
        with open(full_p, "w", encoding="utf-8") as f:
            f.write(content)

    def _materialize_one(f_entry: Dict[str, Any]) -> None:
        rel_path = str(f_entry.get("path") or "").strip()
        if not rel_path:
            return
        status = str(f_entry.get("status") or "modified")
        prev_path = str(f_entry.get("previousPath") or rel_path)

        if status == "added":
            _write_snap(base_root, rel_path, "")
        else:
            b_txt = fetch_gerrit_file_content(
                base_url=base_url,
                project=project,
                change_num=change_num,
                revision_sha_or_ps=head_sha,
                rel_path=prev_path,
                parent=True,
                base_sha=base_sha,
                repo_dir=repo_dir,
            )
            _write_snap(base_root, rel_path, b_txt if b_txt is not None else "")

        if status == "removed":
            _write_snap(head_root, rel_path, "")
        else:
            h_txt = fetch_gerrit_file_content(
                base_url=base_url,
                project=project,
                change_num=change_num,
                revision_sha_or_ps=head_sha,
                rel_path=rel_path,
                parent=False,
                base_sha=base_sha,
                repo_dir=repo_dir,
            )
            _write_snap(head_root, rel_path, h_txt if h_txt is not None else "")

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(_materialize_one, target_files))

    return base_root, head_root


def auto_detect_gerrit_repo_dir(
    gerrit_host: str,
    project: str,
    provided_dir: Optional[str] = None,
) -> str:
    """Detects a matching local git clone for a Gerrit host + project if one exists on disk."""
    proj_leaf = (project or "").rstrip("/").split("/")[-1]
    host_base = (gerrit_host or "").lower().split(":", 1)[0]
    # Note: Gerrit review hosts like `foo-review.googlesource.com` correspond to git remotes at `foo.googlesource.com`
    git_host_alt = host_base.replace("-review.", ".")

    def _matches(cand_dir: str) -> bool:
        if not cand_dir or not os.path.isdir(os.path.join(cand_dir, ".git")):
            return False
        try:
            res = subprocess.run(
                ["git", "remote", "-v"],
                cwd=cand_dir,
                capture_output=True,
                text=True,
                timeout=3,
            )
            remotes = res.stdout.lower()
            if project and project.lower() in remotes and (host_base in remotes or git_host_alt in remotes):
                return True
            if proj_leaf and re.search(rf"[:/]{re.escape(proj_leaf.lower())}(?:\.git)?(?:\s|$)", remotes):
                if host_base in remotes or git_host_alt in remotes:
                    return True
        except Exception:
            pass
        return False

    if provided_dir:
        abs_prov = os.path.abspath(os.path.expanduser(provided_dir))
        if _matches(abs_prov):
            return abs_prov

    home = os.path.expanduser("~")
    for root_name in ("work", "dev", "src", "projects"):
        cand = os.path.join(home, root_name, proj_leaf)
        if _matches(cand):
            return os.path.abspath(cand)

    if provided_dir and os.path.isdir(os.path.join(os.path.expanduser(provided_dir), ".git")):
        return os.path.abspath(os.path.expanduser(provided_dir))
    return os.path.abspath(provided_dir or os.getcwd())


def checkout_gerrit_patchset_in_repo(
    repo_dir: str,
    pr_meta: Dict[str, Any],
    stash_if_dirty: bool = False,
) -> Dict[str, Any]:
    """Fetches a Gerrit change's `refs/changes/...` ref and checks it out into a local branch."""
    if not repo_dir or not os.path.isdir(os.path.join(repo_dir, ".git")):
        return {"ok": False, "error": f"No valid git repository found at {repo_dir}"}

    change_num = int(pr_meta.get("number") or 0)
    ps_num = int(pr_meta.get("patchSet") or 1)
    ref_spec = str(pr_meta.get("headRefName") or f"refs/changes/{change_num % 100:02d}/{change_num}/{ps_num}")
    local_branch = f"gerrit/cl-{change_num}-ps{ps_num}"

    prev_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo_dir, capture_output=True, text=True
    ).stdout.strip()
    if prev_branch == local_branch:
        return {
            "ok": True,
            "alreadyOnBranch": True,
            "previousBranch": prev_branch,
            "checkedOutBranch": local_branch,
            "repoDir": repo_dir,
        }

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    ).stdout.strip()
    stashed = False
    if dirty and stash_if_dirty:
        st_res = subprocess.run(
            ["git", "stash", "push", "-m", f"Quasar auto-stash before Gerrit CL #{change_num}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        stashed = st_res.returncode == 0

    fetch_targets: List[str] = ["origin", "upstream"]
    base_url = str(pr_meta.get("gerritBaseUrl") or "").rstrip("/")
    project = str(pr_meta.get("gerritProject") or pr_meta.get("repo") or "").strip("/")
    if base_url and project:
        git_url = base_url.replace("-review.googlesource.com", ".googlesource.com") + f"/{project}"
        fetch_targets.append(git_url)
        fetch_targets.append(f"{base_url}/{project}")

    for remote in fetch_targets:
        f_res = subprocess.run(
            ["git", "fetch", remote, ref_spec],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if f_res.returncode == 0:
            co_res = subprocess.run(
                ["git", "checkout", "-B", local_branch, "FETCH_HEAD"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
            )
            if co_res.returncode == 0:
                return {
                    "ok": True,
                    "previousBranch": prev_branch,
                    "checkedOutBranch": local_branch,
                    "stashed": stashed,
                    "repoDir": repo_dir,
                }

    return {
        "ok": False,
        "hasUncommittedChanges": bool(dirty and not stashed),
        "error": f"Could not fetch `{ref_spec}` into {repo_dir}.",
        "repoDir": repo_dir,
    }


def fetch_gerrit_live_head_sha(
    base_url: str,
    project: Optional[str],
    change_num: int,
    timeout: float = 5.0,
) -> Tuple[str, int]:
    """Lightweight check returning `(current_revision_sha, latest_patchset_num)` for freshness & cache checks."""
    cid = _change_endpoint_id(project, change_num)
    try:
        ch = gerrit_api_request(base_url, f"/changes/{cid}?o=CURRENT_REVISION", timeout=timeout)
    except Exception:
        if project:
            ch = gerrit_api_request(base_url, f"/changes/{change_num}?o=CURRENT_REVISION", timeout=timeout)
        else:
            return "", 0
    if not isinstance(ch, dict):
        return "", 0
    cur_sha = str(ch.get("current_revision") or "")
    revs = ch.get("revisions") or {}
    ps_num = 0
    if cur_sha and isinstance(revs, dict) and isinstance(revs.get(cur_sha), dict):
        ps_num = int(revs[cur_sha].get("_number") or 0)
    return cur_sha, ps_num


def post_gerrit_review(
    pr_meta: Dict[str, Any],
    staged_threads: List[Dict[str, Any]],
    summary_body: str = "",
    review_event: str = "PENDING",
    prior_draft_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Publishes staged review comments to Gerrit.

    - `PENDING`: Saves staged comments as Gerrit **Draft Comments** (`PUT /a/changes/{id}/revisions/{rev}/drafts`),
      replacing any `prior_draft_ids` created earlier in the same Quasar session so re-exporting never duplicates drafts.
    - `COMMENT` / `APPROVE` / `REQUEST_CHANGES`: Submits an atomic Gerrit review
      (`POST /a/changes/{id}/revisions/{rev}/review`), cleaning up any `prior_draft_ids` first.
    """
    base_url = str(pr_meta.get("gerritBaseUrl") or "").rstrip("/")
    project = str(pr_meta.get("gerritProject") or pr_meta.get("repo") or "").strip()
    change_num = int(pr_meta.get("number") or 0)
    rev_id = str(pr_meta.get("headSha") or pr_meta.get("patchSet") or "current").strip()
    if not base_url or change_num <= 0:
        raise RuntimeError("Missing Gerrit change metadata (`gerritBaseUrl` / `number`).")

    cid = _change_endpoint_id(project or None, change_num)
    auth = resolve_gerrit_auth(base_url)
    if not auth.get("authenticated"):
        parsed_h = urllib.parse.urlparse(base_url).netloc or base_url
        raise RuntimeError(
            f"NO_GERRIT_AUTH: Publishing to Gerrit ({parsed_h}) requires authentication. "
            f"Configure `~/.gitcookies`, `~/.netrc`, or run: "
            f"`python3 post_pending_review.py --set-gerrit-auth {parsed_h} <username> <http-password>`."
        )

    event_upper = (review_event or "PENDING").strip().upper()
    inline_items: List[Dict[str, Any]] = []
    top_level_notes: List[str] = []
    if summary_body.strip():
        top_level_notes.append(summary_body.strip())

    for t in staged_threads:
        if t.get("id") == "top-level-review":
            draft_txt = str(t.get("draftComment") or t.get("body") or "").strip()
            if draft_txt and draft_txt not in top_level_notes:
                top_level_notes.append(draft_txt)
            continue
        rel_path = str(t.get("path") or "").strip()
        body_txt = str(t.get("draftComment") or t.get("body") or "").strip()
        if not body_txt:
            continue
        if t.get("isTopLevel") or not rel_path or rel_path == "TOP_LEVEL_PR_COMMENTS.md":
            tf = str(t.get("targetFile") or "").strip()
            note = f"`{tf}`: {body_txt}" if (tf and tf not in body_txt) else body_txt
            if note not in top_level_notes:
                top_level_notes.append(note)
            continue

        s_line = max(1, int(t.get("startLine") or t.get("endLine") or 1))
        e_line = max(s_line, int(t.get("endLine") or s_line))
        c_entry: Dict[str, Any] = {
            "path": rel_path,
            "line": e_line,
            "message": body_txt,
            "unresolved": True,
        }
        if e_line > s_line:
            c_entry["range"] = {
                "start_line": s_line,
                "start_character": 0,
                "end_line": e_line,
                "end_character": 0,
            }
        inline_items.append(c_entry)

    combined_body = "\n\n".join(p for p in top_level_notes if p).strip()

    # Delete prior Quasar-created drafts on this revision before replacing or submitting
    replaced_draft_ids: List[str] = []
    for old_did in prior_draft_ids or []:
        if not old_did:
            continue
        try:
            gerrit_api_request(
                base_url,
                f"/changes/{cid}/revisions/{rev_id}/drafts/{urllib.parse.quote(str(old_did), safe='')}",
                method="DELETE",
                expect_json=False,
                require_auth=True,
            )
            replaced_draft_ids.append(str(old_did))
        except Exception:
            pass

    change_html_url = str(pr_meta.get("url") or f"{base_url}/c/{project}/+/{change_num}")
    published_as = str(auth.get("username") or auth.get("source") or "")
    try:
        self_acct = gerrit_api_request(base_url, "/accounts/self", require_auth=True, timeout=6.0)
        if isinstance(self_acct, dict):
            published_as = _format_gerrit_account(self_acct)
    except Exception:
        pass

    if event_upper == "PENDING":
        new_draft_ids: List[str] = []
        for item in inline_items:
            draft_in = dict(item)
            resp_d = gerrit_api_request(
                base_url,
                f"/changes/{cid}/revisions/{rev_id}/drafts",
                method="PUT",
                payload=draft_in,
                require_auth=True,
            )
            if isinstance(resp_d, dict) and resp_d.get("id"):
                new_draft_ids.append(str(resp_d["id"]))

        if combined_body:
            # Try `/PATCHSET_LEVEL` first (Gerrit 3.3+), falling back to `/COMMIT_MSG` on older Gerrit
            top_saved = False
            for pseudo_path in ("/PATCHSET_LEVEL", "/COMMIT_MSG"):
                try:
                    resp_top = gerrit_api_request(
                        base_url,
                        f"/changes/{cid}/revisions/{rev_id}/drafts",
                        method="PUT",
                        payload={"path": pseudo_path, "message": combined_body, "unresolved": False},
                        require_auth=True,
                    )
                    if isinstance(resp_top, dict) and resp_top.get("id"):
                        new_draft_ids.append(str(resp_top["id"]))
                        top_saved = True
                        break
                except Exception:
                    continue
            if not top_saved and not new_draft_ids:
                raise RuntimeError("Gerrit server rejected draft comment creation.")

        return {
            "ok": True,
            "provider": "gerrit",
            "status": "pending_review_updated" if replaced_draft_ids else "pending_review_created",
            "event": "PENDING",
            "published_as": published_as,
            "gerrit_draft_ids": new_draft_ids,
            "replaced_pending_review_ids": replaced_draft_ids,
            "state": "DRAFT",
            "html_url": change_html_url,
            "comments_exported": len(inline_items),
            "has_top_level_body": bool(combined_body),
            "review_body": combined_body,
        }

    # Immediate review submission (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`)
    comments_by_path: Dict[str, List[Dict[str, Any]]] = {}
    for item in inline_items:
        p = str(item["path"])
        c_copy = {k: v for k, v in item.items() if k != "path"}
        comments_by_path.setdefault(p, []).append(c_copy)

    review_input: Dict[str, Any] = {"drafts": "KEEP"}
    if combined_body:
        review_input["message"] = combined_body
    if comments_by_path:
        review_input["comments"] = comments_by_path

    approve_score = int(auth.get("approveScore") or 1)
    if event_upper == "APPROVE":
        review_input["labels"] = {"Code-Review": approve_score}
    elif event_upper == "REQUEST_CHANGES":
        review_input["labels"] = {"Code-Review": -1}

    try:
        resp_rev = gerrit_api_request(
            base_url,
            f"/changes/{cid}/revisions/{rev_id}/review",
            method="POST",
            payload=review_input,
            require_auth=True,
        )
    except Exception as exc:
        # If the Gerrit project uses custom label names instead of `Code-Review` or restricts the score,
        # retry `+1` if `+2` failed, or retry without `labels` so comments are never lost.
        if review_input.get("labels"):
            if event_upper == "APPROVE" and approve_score > 1:
                retry_plus1 = dict(review_input)
                retry_plus1["labels"] = {"Code-Review": 1}
                try:
                    resp_rev = gerrit_api_request(
                        base_url,
                        f"/changes/{cid}/revisions/{rev_id}/review",
                        method="POST",
                        payload=retry_plus1,
                        require_auth=True,
                    )
                except Exception:
                    retry_no_lbl = {k: v for k, v in review_input.items() if k != "labels"}
                    resp_rev = gerrit_api_request(
                        base_url,
                        f"/changes/{cid}/revisions/{rev_id}/review",
                        method="POST",
                        payload=retry_no_lbl,
                        require_auth=True,
                    )
            else:
                retry_no_lbl = {k: v for k, v in review_input.items() if k != "labels"}
                if retry_no_lbl.get("message") or retry_no_lbl.get("comments"):
                    resp_rev = gerrit_api_request(
                        base_url,
                        f"/changes/{cid}/revisions/{rev_id}/review",
                        method="POST",
                        payload=retry_no_lbl,
                        require_auth=True,
                    )
                else:
                    raise exc
        else:
            raise

    return {
        "ok": True,
        "provider": "gerrit",
        "status": "review_published",
        "event": event_upper,
        "published_as": published_as,
        "gerrit_draft_ids": [],
        "replaced_pending_review_ids": replaced_draft_ids,
        "state": event_upper,
        "labels": (resp_rev or {}).get("labels") if isinstance(resp_rev, dict) else {},
        "html_url": change_html_url,
        "comments_exported": len(inline_items),
        "has_top_level_body": bool(combined_body),
        "review_body": combined_body,
    }


def poll_gerrit_host_open_changes(
    host_or_url: str,
    watch_requested: bool = True,
    watch_authored: bool = True,
    custom_query: str = "",
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """Optional Inbox polling helper for configured Gerrit hosts (`gerritHosts` in Inbox settings).
    Returns normalized Inbox items for open Gerrit changes involving `self`.
    Zero network calls are made unless the user explicitly configures `gerritHosts`.
    """
    _hk, base_url = _normalize_host_key(host_or_url)
    auth = resolve_gerrit_auth(base_url)
    queries: List[Tuple[str, str]] = []
    if auth.get("authenticated"):
        if watch_requested:
            queries.append(("review_requested", "is:open -is:wip (reviewer:self OR cc:self) -owner:self"))
        if watch_authored:
            queries.append(("authored", "is:open owner:self"))
    if custom_query.strip():
        queries.append(("custom_query", custom_query.strip()))

    if not queries:
        return []

    parsed_netloc = urllib.parse.urlparse(base_url).netloc or _hk
    by_id: Dict[str, Dict[str, Any]] = {}
    for source_tag, q_str in queries:
        q_enc = urllib.parse.quote(q_str, safe="")
        ep = (
            f"/changes/?q={q_enc}&n={int(limit)}"
            f"&o=CURRENT_REVISION&o=DETAILED_ACCOUNTS&o=DETAILED_LABELS"
        )
        try:
            rows = gerrit_api_request(base_url, ep, timeout=10.0)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for ch in rows:
            if not isinstance(ch, dict):
                continue
            c_num = int(ch.get("_number") or 0)
            proj = str(ch.get("project") or "").strip()
            if c_num <= 0 or not proj:
                continue
            iid = make_gerrit_session_id(parsed_netloc, proj, c_num)
            cur_sha = str(ch.get("current_revision") or "")
            revs = ch.get("revisions") or {}
            ps_num = 1
            if cur_sha and isinstance(revs, dict) and isinstance(revs.get(cur_sha), dict):
                ps_num = int(revs[cur_sha].get("_number") or 1)
            existing = by_id.get(iid)
            if existing:
                srcs = existing.setdefault("matchedSources", [])
                if source_tag not in srcs:
                    srcs.append(source_tag)
                continue
            role = "author" if source_tag == "authored" else "reviewer"
            unresolved_cnt = int(ch.get("unresolved_comment_count") or 0)
            total_cnt = int(ch.get("total_comment_count") or 0)
            updated_raw = str(ch.get("updated") or "").replace(" ", "T")
            if updated_raw and not updated_raw.endswith("Z"):
                updated_raw = re.sub(r"\.\d+$", "", updated_raw) + "Z"
            by_id[iid] = {
                "id": iid,
                "provider": "gerrit",
                "gerritBaseUrl": base_url,
                "owner": parsed_netloc.lower(),
                "repo": proj,
                "number": c_num,
                "patchSet": ps_num,
                "title": str(ch.get("subject") or f"{proj} #{c_num}"),
                "url": f"{base_url}/c/{proj}/+/{c_num}",
                "author": _format_gerrit_account(ch.get("owner")),
                "role": role,
                "matchedSources": [source_tag],
                "headSha": cur_sha,
                "baseRefName": str(ch.get("branch") or "main"),
                "headRefName": f"PS#{ps_num}",
                "additions": int(ch.get("insertions") or 0),
                "deletions": int(ch.get("deletions") or 0),
                "reviewCommentsCount": total_cnt,
                "unresolvedCommentsCount": unresolved_cnt,
                "hasExternalFeedback": bool(total_cnt > 0),
                "updatedAt": updated_raw,
            }

    return list(by_id.values())
