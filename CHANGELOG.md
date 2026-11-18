# Changelog

All notable changes to **Quasar** are documented in this file.

## [1.7.3] - 2026-11-18

### Fixed
- **Restore Direct Antigravity IDE Sidebar Chat Dispatch (`daemon/hub_*.json` Discovery)**:
  - Updated `discoverAntigravityLsEnv()` (`extension.js`) and `discover_ls_env()` (`server.py`) to read live `~/.gemini/antigravity/daemon/hub_*.json` metadata (where Antigravity 2.0 `agy --hub` writes `httpPort` and `csrfToken` instead of passing `--csrf_token` on the CLI) and prioritize exact workspace path matches over substring matches—restoring direct dispatch to the visible IDE Sidebar Chat instead of falling back to headless `agy --print`.
- **Prevent Premature `⚠️ Check Fix` During Long Thinking Turns**:
  - Updated `inspectConversationFixState()` (`extension.js`) to remain `'working'` while an active `agy` CLI job is running and raised the thinking-turn idle timeout from 90s to 240s.

## [1.7.2] - 2026-11-18

### Fixed
- **Headless `agy` CLI Fix Agent Aborting on Inspection/Build Commands & Stuck `⏳ Fixing...` State**:
  - Switched headless `agy --print` fix runs in `extension.js` and `server.py` from `--mode=accept-edits` to `--mode=auto` and expanded `allowRules` with standard read-only and build/test commands (`ls`, `find`, `rg`, `grep`, `cat`, `head`, `tail`, `wc`, `diff`, `swift`, `xcodebuild`, `gradle`, `./gradlew`, `cmake`, `mvn`, `bazel`, `ruby`, `bundle`, `pod`, etc.) so fix agents don't abort mid-run before applying edits.
  - Added automatic `manage_fixes.py --reconcile-fixes --agent-idle` when `allowRepoEdits` CLI jobs exit and added a stale-transcript guard (>5m with no active CLI job) in `inspectConversationFixState()` so aborted tool calls never stay stuck on `⏳ Fixing with Agent Now`.

## [1.7.1] - 2026-11-17

### Added
- **Live Background Auto-Review Status & Countdown Timers (`liveStatus`)**:
  - Replaced the static Inbox status row across VS Code (`PR Inbox` header, auto-refreshing every 30s while visible), the standalone Flutter/Web app, and `quasar watch --status` with live phase & timer telemetry: `Xm into reviewing <PR>` (with active model & effort), `Xm until next review (N eligible PRs waiting)`, `Out of tokens — waiting Xh Ym to retry`, `Daily cap reached`, or `Caught up • Xm until next check`.
- **Separate `⚡ Queued for Auto-Review` vs. `📥 Browse Only / Manual ⚡` Inbox Sections**:
  - Split unreviewed Inbox PRs into **`⚡ Queued for Auto-Review`** (only PRs actually eligible for automatic background pre-review) and **`📥 Browse Only / Manual ⚡ (Auto-Review Off)`** (collapsed by default in VS Code so `Inbox-only` or >cutoff PRs never look stuck in the automatic queue while keeping 1-click `⚡` manual pre-review).

### Fixed
- **Automatic Recovery After Model Quota Resets**:
  - Parses exact `"reset after XhYmZs"` durations from `agy` quota-exhaustion errors and automatically resumes reviewing once `retryAfter` elapses instead of permanently pausing PRs after 3 quota retries.
- **Include Inline Thread Conversations in Agent Fix Prompts (`manage_fixes.py`)**:
  - `--prepare-fix` now embeds follow-up inline Q&A / thread discussion messages directly into the fix agent prompt (filtering out pending placeholders and avoiding duplication of the primary finding card) and instructs the agent to honor decisions made in the inline conversation.

## [1.7.0] - 2026-11-17

### Added
- **Host-Agnostic Gerrit Code Review Support (`gerrit_adapter.py`)**:
  - Added [`plugin/skills/quasar/scripts/gerrit_adapter.py`](plugin/skills/quasar/scripts/gerrit_adapter.py) while keeping Quasar's UX and defaults GitHub-first (0 Gerrit network calls unless a Gerrit change URL is opened or `gerritHosts` is configured).
  - Supports any standard Gerrit 2.16+ / 3.x server (`https://<host>[/<prefix>]/c/<project>/+/<change>[/<patchset>]`, `/+/<change>`, legacy `/#/c/...`, and patchset ranges), automatic XSSI `)]}'` stripping, threaded inline comments (`in_reply_to` + `unresolved` status), base/head file snapshot materialization, patchset-to-patchset incremental delta reviews, stale patchset freshness checks, and optional `gerritHosts` Inbox polling.
  - Agnostic authentication resolution across `~/.gemini/quasar/gerrit_auth.json` (`--set-gerrit-auth`), `git config http.cookiefile` / `~/.gitcookies` (including `#HttpOnly_` cookies), `~/.netrc`, environment variables, HTTP Basic/Digest auth, and anonymous public fallback, plus publishing staged comments as Gerrit **Draft Comments** (`PENDING`) or full reviews (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`).
- **CLI Model, Quota-Fallback & Agent Selection + Background Failure / Quota Alerts (`quasar.configureInboxModel`, `quasar watch --model` / `--agent`)**:
  - Added live CLI capability discovery (`agy models` & `agy agents`) and user-configurable `cliModel`, `cliFallbackModels`, and `cliAgent` settings across `inbox_watcher.py`, VS Code (`Quasar: Choose CLI Model, Quota Fallback & Agent...`), `quasar-web`, the standalone Flutter app, and `quasar watch` (`--model`, `--fallback-models`, `--agent`, `--list-models`). Changing the configured model or agent automatically clears any active quota cooldowns so paused items can retry immediately.
  - Added prominent failure & token/quota-exhaustion visibility across all UIs: warning icons, error badges, retry countdowns, and a top-level **Out of Model Quota** alert banner (with 1-click **Switch CLI Model / Agent** and **Retry Now** actions) in the VS Code `PR Inbox` tree, desktop warning toasts (`notifyOnError`), and the standalone Flutter app, plus a cycle-level quota circuit breaker so remaining queued PRs aren't repeatedly failed when quota runs out.
- **1-Click Inline Unstage Button**: Added an inline **Unstage** hover button (`quasar.unstageThread`) directly on `Staged for GitHub Review` rows in the VS Code `Review Comments & Cart` sidebar so comments can be moved back to `Open Candidates` without deleting them.

### Fixed
- **Inline Comment Replies Stuck on `⏳ Quasar is analyzing...` Upon CLI Model Quota Exhaustion**:
  - `dispatchViaAgyCli` (`extension.js`), `dispatch_agy_background` (`server.py`), and `run_precompute_for_item` (`inbox_watcher.py`) previously resolved as soon as `agy` emitted its `init` event and ignored `429 RESOURCE_EXHAUSTED` (`code 3`) exits on the CLI's default model—leaving inline comment replies stuck on `⏳ Quasar is analyzing...`.
  - Quasar now automatically retries across configured or auto-discovered `agy` fallback models on model-quota exhaustion, captures plain-text agent responses if `answer_comment_question.py` wasn't invoked, and guarantees any remaining `pending: true` thread placeholder is reconciled on process exit.

## [1.6.1] - 2026-11-17

### Added
- **Granular PR Source Flags & Separate `📥 Inbox` vs. `⚡ Auto-Review` Controls**:
  - Split PR Inbox discovery and background auto-review toggles independently per GitHub source across `inbox_watcher.py`, VS Code (`quasar.configureInboxWatcher`), `quasar-web`, the standalone Flutter app, and `quasar watch`:
    - `review-requested:@me` (**Auto-Review ON** by default)
    - `reviewed-by:@me`, `commenter:@me`, `mentions:@me` / `assignee:@me`, `author:@me`, `watchedRepos`, and `customQuery` (**0-token Inbox Sync ON, Auto-Review OFF** by default until opted in).
  - Added multi-role attribution (`matchedRoles` / `roleLabel`, e.g. `Review Requested + Reviewed by @me`), `authoredPrMode` (`feedback_only` vs. `all_open` self-review on push), custom GitHub search queries (`customQuery` with `@me` token expansion), and global `extraSearchFlags` (with non-`304` search pacing to protect against GitHub secondary rate limits).

## [1.6.0] - 2026-11-16

### Added
- **Background Auto-Review Daemon & Multi-PR Inbox (`inbox_watcher.py` & `quasar watch`)**:
  - Added [`plugin/skills/quasar/scripts/inbox_watcher.py`](plugin/skills/quasar/scripts/inbox_watcher.py), `--session-dir` / `QUASAR_SESSION_DIR` isolation in `collect_pr_context.py` and `publish_review_session.py`, and `quasar watch` CLI commands (`--sync`, `--once`, `--stop`, `--status`, `--configure`) so background pre-reviews run in isolated storage (`~/.gemini/quasar/inbox/items/<id>/`) without ever overwriting an open window's `active_session.json`, loading into any workspace in **0 seconds** when clicked.
  - **User-Configurable Scope, Priority & Token-Consumption Safeguards**: Defaults to `review-requested:@me`, PRs involving `@me` (`watchInvolvedPrs: true` via `involves:@me -author:@me`—capturing triage comment assignments, `@mentions`, and prior review rounds where GitHub clears `review-requested:@me`), and user-authored open PRs with new comments at `high` effort. Ranks background auto-review priority (`updatedSinceLastReview` / `changesRequested` > `author` > explicit `review-requested:@me` > `involves:@me` > `watched_repo`) while protecting against large-backlog token bursts (`maxConcurrency: 1`, `maxReviewsPerCycle: 1` per `pollIntervalMinutes: 15`, `maxReviewsPerDay: 6`, `onlyUpdatedWithinDays: 14`, plus a `sync_queue_only` 0-token mode and automatic `security_gate.py` quarantine before any background `agy` run). Every setting is configurable via VS Code (`quasar.configureInboxWatcher`), `quasar-web`, the standalone Flutter app, and `quasar watch`.
  - **Two-Stage List-First Sync + HTTP `ETag` (`304 Not Modified`) Caching**: Fetches lightweight `/search/issues` PR lists first (stopping pagination at page 1 on incremental polls once reaching `lastSyncedAt`, with `If-None-Match` `ETag` caching so unchanged polls consume **0** GitHub rate-limit points) and digs into `/repos/{owner}/{repo}/pulls/{num}` **only** when a PR's `updated_at` changed *and* it has prior review state or is an active authored PR—deferring full PR context/diff fetches on unreviewed queued PRs until they are selected for review.
  - **Multi-PR Inbox Across All UI Surfaces**: Added the `PR Inbox & Auto-Review` sidebar TreeView (with Activity Bar unread ready badge & desktop ready toasts) in VS Code, the `📥 PR Inbox` tab & Settings modal in `quasar-web`, and `InboxView` in the standalone Flutter app.
  - **Two-Way Completed-Review Reuse & Freshness-Aware Prompts (`--check-existing` & `--activate-session`)**: Requesting a review for an already-reviewed GitHub PR or local branch across VS Code (`quasar.loadPrFromUrl` & `quasar.reviewLocalBranch`), `quasar-web`, the standalone Flutter app, `quasar` CLI (`--force` to bypass), or chat (`SKILL.md`) detects completed reviews across the Inbox, Active Workspaces, and History—offering **Open Existing Review (0s)**, **Updated Review**, or **Clean New Review** when non-stale, and **Updated Review (`oldSha → newSha`)** or **Clean New Review** when on a stale hash. Conversely, `inbox_watcher.py` adopts matching manually-completed `headSha` sessions into the Inbox for **0 tokens**, and `publish_review_session.py` keeps tracked Inbox items synced whenever a manual review finishes.
- **Skeptical but Context-Aware PR Description Handling (`SKILL.md`, `review-advocate`, `review-bug-hunter`, `review-test-critic`)**: Explicitly instructs non-blind lenses and synthesis to verify PR description claims against the code rather than taking them at face value, while acknowledging stated trade-offs, constraints, or follow-up plans in draft comment phrasing when an intermediate state still warrants feedback.
- **Incremental / Delta Re-Reviews (`oldSha → newSha`) & Full Stale-Hash Safeguards**:
  - **Incremental Delta Engine (`collect_pr_context.py --incremental` / `--incremental-from`, `publish_review_session.py`, `SKILL.md`)**: Computes exact `oldSha → newSha` file & patch deltas (handling both fast-forward commits and rebased force-pushes), remaps line numbers with `difflib.SequenceMatcher`, carries forward read tour progress and staged/dismissed comments on untouched files, reconciles prior findings on modified files (`priorFindingUpdates`—automatically unstaging and flagging `[✅ Resolved?]` on staged comments fixed by the new commit), prepends a `🆕 Changes Since <oldShort> → <newShort>` chapter, and renders `cliffsNotes.deltaSummary`. Also enabled automatically in `inbox_watcher.py` (`incrementalUpdates: true`) when new commits arrive on an already pre-reviewed Inbox PR.
  - **Stale-Hash Safeguards**: Added SHA-keyed snapshot directories (`snapshots/<session_id>-<headSha[:8]>` with automatic pruning of older SHA snapshots so background runs never overwrite open editor snapshots), `commit_id` pinning (with force-push fallback) in `post_pending_review.py`, stale-session prompts in `activate_inbox_item` (`staleSessionAvailable`), and an **`⚠️ Newer Commits Pushed on GitHub (oldSha → newSha)`** banner with 1-click **`⚡ Update Incrementally`** across VS Code, `quasar-web`, and the standalone Flutter app.
- **Delete & Prune Saved Reviews (`quasar.deleteReview`, `quasar.manageSavedReviews`, `quasar clean`, `quasar delete`)**:
  - Added 1-click per-review permanent deletion (`history/`, `inbox/items/`, `snapshots/`, and active workspace state—preserving learned preferences) via inline `🗑️` icons on Past Reviews & QuickPicks in VS Code, the `🗑️` Saved Reviews manager in `quasar-web` and the standalone Flutter app, `Delete Active Review Permanently` in `Reset / Close Review`, and bulk pruning (`Prune > 7 / 14 / 30 days` or `Delete All Past Reviews`, plus `quasar clean` and `quasar delete` on the CLI).
  - **Deleted Reviews Pool in Auto-Review Inbox (`inboxGroup: "deleted"`, `quasar.requeueInboxItem`)**: Deleting a review for an open GitHub PR repopulates it under **`🗑️ Deleted Reviews`** in the Auto-Review Inbox (preventing unwanted automatic token burn while keeping it visible) with 1-click options to **`➕ Re-Add to Auto-Review Queue`** or **`⚡ Re-Review Now`**.

## [1.5.0] - 2026-11-13

### Added
- **Live Agent Fix Progress, Completion Notifications & Auto-Reconciliation**:
  - **Distinct Live Fix States**: Separated unsent `Queued to Send` comments from `⏳ Fixing with Agent Now`, `💬 Agent Waiting for Chat Reply` (when paused on `ask_question`), `⚠️ Agent Turn Ended — Needs Check`, and `✅ Fixed in Working Tree` across the VS Code `Review Comments & Cart` sidebar, spinning Status Bar (`Fixing N...` / `N Fixed`), inline `CommentThread` banners, Interactive Study Guide, `quasar-web`, and the standalone Flutter app (which also now retains a dedicated `✅ Fixed in Working Tree` sidebar section instead of hiding completed items).
  - **Completion Toast Notifications**: Added immediate completion notifications (`✅ Quasar finished fixing N comment(s) in <repo>!` with 1-click `Inspect Fixed Diff` jump action) across VS Code, `quasar-web`, and the Flutter standalone app, plus `✓ Mark as Fixed` (`quasar.markCommentFixed`) for manual 1-click completion.
  - **Fallback Working-Tree Auto-Reconciliation (`manage_fixes.py --reconcile-fixes`)**: Recorded baseline SHA-256 hashes on `--prepare-fix` and added a background transcript/file-hash reconciler in `extension.js` and `server.py` so even if an agent finishes editing files without running `--complete-fix`, Quasar automatically syncs the updated files into `headSnapshotRoot`, marks the comments `✅ Fixed`, and notifies you instead of leaving `Fixing...` stuck indefinitely.
- **Deterministic Pre-Review Security & Prompt-Injection Gate (`security_gate.py`)**:
  - Added [`plugin/skills/quasar/scripts/security_gate.py`](plugin/skills/quasar/scripts/security_gate.py) running deterministically in Python inside `collect_pr_context.py` **before** any LLM review agent or subagent is invoked:
    - **Quarantine Circuit-Breaker (`status: "blocked"`, `haltLlmReview: true`)**: Detects prompt-injection / agent-hijack directives (including hidden HTML comments), Trojan-Source bidirectional / Unicode Tag control characters, remote shell-pipe execution (`curl | sh`), obfuscated `eval`/`exec` payloads, and `pull_request_target` untrusted head checkouts. Immediately halts LLM review (in `extension.js`, `quasar-web`, and `SKILL.md`, while redacting untrusted prose from `pr_context.json`) so poisoned content is never fed to review subagents, and displays a red quarantine banner with inert excerpts, click-to-inspect read-only diff links, and a manual `Override Quarantine & Run Review` (`--override-quarantine` / `quasar.overrideQuarantine`) escape hatch.
    - **Build / CI / Agent-Config Warning (`status: "warning"`)**: Flags edits to CI workflows, build/install lifecycle hooks (`package.json` `preinstall`/`postinstall`, `CMakeLists.txt`, `build.gradle*`, `Makefile`, `setup.py`, `build.rs`), Git/IDE hooks (`.vscode/tasks.json`, `.husky/*`), and repository agent configs (`AGENTS.md`, `CLAUDE.md`, `.gemini/*`), suppressing automatic branch checkout prompts and reminding reviewers to inspect those hunks before running local commands.
    - **Silent When Clean (`status: "none"`)**: Never displays a false-confidence "Safe" badge when no heuristics fire.
- **Built-In Blind-Diff & Intent-vs-Actuality Subagent (`review-blind-diff`)**:
  - Added [`plugin/agents/review-blind-diff/agent.md`](plugin/agents/review-blind-diff/agent.md) (enabled at `medium` and `high` effort by default with `quasarBlindDiff: true` in `review_lenses.py`), evaluating the raw code diff under a strict information firewall (without PR title, description, commit messages, or comments) to uncover what the code actually does, catch half-wired features, and flag hidden side effects or scope creep.
  - Added `cliffsNotes.intentVsActuality` synthesis and rendering across `SKILL.md`, `publish_review_session.py`, `collect_pr_context.py`, the VS Code sidebar & Interactive Study Guide, `quasar-web`, and the standalone Flutter app—comparing `review-blind-diff`'s unanchored Actuality Report against the author's stated PR intent.
- **In-Diff Guided Tour Controls & Mode-Aware Action Disambiguation**:
  - Added `← Previous Tour Stop`, `→ Next Tour Stop`, and `📖 Open CliffsNotes Study Guide` buttons directly to the diff editor's top-right toolbar (`editor/title` when viewing a Quasar review diff), plus stop counters (`Stop X/Y`) and `⬅️ Prev` / `➡️ Next` actions in Tour Stop CodeLenses, Hover cards, `quasar-web`, and the standalone Flutter app's pinned Diff Tour Strip (`Alt+Down` / `Alt+Up`).
  - Synced `currentStopIndex` whenever jumping to a stop from the Study Guide, flowchart, or sidebar so `Prev` and `Next` always step sequentially from the currently viewed stop.
  - Decluttered the `Review Comments & Cart` and `CliffsNotes & Reading Tour` sidebar headers (moving secondary/destructive actions to the labeled `⋯` overflow menu) and added distinct, mode-aware full-text primary action rows at the top of `Review Comments & Cart` (`🔧 Send Checked Comments to Agent to Fix...` for owned branches/PRs vs. `☁️ Publish Review to GitHub (N Staged)...` for GitHub PRs).
- **First-Class Inline Comment Authoring & "Ask Quasar to Add Comment"**:
  - Added **`+ Add Review Comment`** (`quasar.stageNewComment` / `quasar.addCommentAtLine`) and **`✨ Ask Quasar to Add Comment`** (`quasar.askToAddComment` / `quasar.askToAddCommentAtLine`) across the native VS Code `+` gutter box, editor context menu, Hover cards, Tour Stop CodeLenses, **Review Comments & Cart** sidebar header, `quasar-web`, and the standalone Flutter app (`DiffViewer`).
  - Added `--create` (`--path`, `--start-line`, `--end-line`) and `--promote-to-comment` to `answer_comment_question.py` (and `SKILL.md`) so Quasar can also create or populate inline review comments directly from chat or inline `+` threads.
- **Unified Comment Interaction Parity**:
  - User-added and Quasar-drafted inline comments now share the exact same canonical review-comment schema and lifecycle as review-lens findings—supporting stage/unstage, in-place draft editing (`messages[0]` sync), **💬 Ask Agent to Change Comment**, **🔧 Queue for Agent Fix / Fix Now** (in Author Self-Review mode), **👍 / 👎 / 🧠 Teach Quasar / 🎓 Teach Subagent**, and **☁️ Publish to GitHub**, while staying preserved across session re-publishes.

### Fixed
- **Headless Antigravity CLI (`agy`) Auto-Dispatch Fallback in VS Code & Web Sidecar**:
  - Added `dispatchViaAgyCli` to `sendPromptToQuasar` in [`extension/extension.js`](extension/extension.js) so VS Code windows without an embedded `ANTIGRAVITY_LS_ADDRESS` / `ANTIGRAVITY_CSRF_TOKEN` language server (such as standard VS Code running alongside Antigravity 2.0 or after a server restart) automatically dispatch reviews, inline Q&A, comment drafting, and code fixes via `agy` instead of falling back to clipboard copy.
  - Fixed `agy --print` flag formatting (`--print=<prompt>` so `--print` never consumes `--output-format`), removed unsupported CLI `--effort` flag failures across models, and added tightly-scoped per-session `--settings` `permissions.allow` rules in both `extension.js` and `server.py` so headless `agy` invocations can run Quasar's scripts cleanly without modifying saved user settings.

## [1.4.0] - 2026-11-12

### Added
- **Inline Subagent Attribution (`sourceAgents` / `sourceAgent`)**:
  - Every finding now records which specialist `review-*` lens(es) surfaced it (preserving multiple lenses when duplicate findings are merged) and displays `🤖 <subagent>` badges across native VS Code inline `CommentThread` banners and author headers, sidebar items, interactive Study Guide cards, `quasar-web`, and the standalone Flutter app.
- **Per-Subagent Continuous Learning & `AGENT.md` Evolution (`quasar.teachSubagent` & `--subagent`)**:
  - Added **🎓 Teach / Tune Review Subagent...** directly inside inline comment cards, comment thread toolbars, sidebar context menus, the **Review Subagents** tree, `quasar-web`, and the Flutter app—plus 1-click subagent-only scoping inside **👍 Helpful**, **👎 Not Useful**, and **🤔 Calibrate Preference**.
  - Added `--subagent <review-*>` support, `subagentRules`, and `subagentStats` telemetry in `manage_preferences.py` (`~/.gemini/quasar/preferences.json` and `PREFERENCES.md`), automatic `learnedDirectives` injection per lens in `review_lenses.py` / `pr_context.json`, and 1-click Antigravity subagent evolution to refine a lens's `AGENT.md` alongside its upgrade-safe learned directives.

### Changed
- **High Effort by Default (`high`)**:
  - Updated the default review effort level from `medium` to `high` across `bin/quasar`, the VS Code / Antigravity extension, `manage_preferences.py`, `collect_pr_context.py`, `publish_review_session.py`, `quasar-web`, and the standalone Flutter app.

### Fixed
- **Deterministic Sidebar-to-Comment Scrolling (`revealRangeInVisibleEditor` & `jumpToCommentThread`)**:
  - Clicking a comment in the sidebar now prefers `vscode.window.activeTextEditor`, centers `range.end.line` on multi-line threads (where VS Code anchors inline `CommentThread` widgets), and verifies `editor.visibleRanges` across async diff folding and ZoneWidget layout passes so comments consistently land in view.

## [1.3.0] - 2026-11-10

### Added
- **Standalone Flutter App (Zero-Install Web + Native Desktop) Powered by Antigravity CLI (`agy`)**:
  - Added [`app/`](app/) (Flutter Web & Desktop client) and [`bin/quasar`](bin/quasar) launcher so Quasar runs completely standalone—either in any browser at `http://127.0.0.1:49341` (with zero IDE or desktop install required) or as a native desktop app (`./bin/quasar --desktop`).
  - Upgraded `plugin/sidecars/quasar-web/server.py` with direct headless Antigravity CLI (`agy --print --output-format stream-json`) auto-dispatch and live NDJSON progress streaming whenever no IDE language server is active, plus static serving of compiled `app/build/web` (`flutter_web`) and `/api/reply-thread` + `/api/open-in-editor` endpoints.
- **Dual-Artifact Release Packaging & One-Line Standalone Installer**:
  - Added [`install-standalone.sh`](install-standalone.sh) and `--standalone-only` / `--vscode-only` modes in [`install.sh`](install.sh) so releases publish both `quasar-<version>.vsix` (VS Code / Antigravity IDE) and `quasar-standalone-<version>.tar.gz` (precompiled Web App + `quasar` CLI).

### Fixed
- **Smooth Comment Navigation & Zero-Jump Inline Q&A Updates**:
  - Clicking any comment in the sidebar or Study Guide now expands collapsed threads and re-centers the diff editor viewport after Monaco finishes laying out diff hunks and inline `CommentThread` widgets (`revealRangeInVisibleEditor`).
  - `syncNativeCommentThreads` now updates `CommentThread` instances in place (reusing native `'+'` gutter widgets, preserving user expand/collapse state, initializing `lastSessionId` on startup, and suppressing self-triggered `fs.watch` bounces) so asking inline questions and receiving agent replies never tear down widgets or jump your scroll position.

## [1.2.5] - 2026-11-09

### Added
- **Structured Quasar Follow-Ups & Code-Level Verification on Existing GitHub PR Comments**:
  - Every pulled GitHub PR comment (`github_existing`) is now followed immediately by a structured **🤖 Quasar Follow-Up** message detailing **✅ What's Done**, **⚠️ What Isn't Done**, and **👉 What Should Be Done** across native VS Code inline comment threads, Study Guide cards, sidebar hover tooltips, CliffsNotes Markdown, and `quasar-web`.
  - Added a first-class `"partially_addressed"` (`🟡 [Partially Addressed]`) triage status so comments where code was updated in HEAD—but an edge case or cleaner refinement remains—explicitly credit what is already done instead of appearing unfixed.
  - Added direct HEAD snapshot & diff-hunk code checks (`inspect_comment_code_state` and `enrich_comments_with_code_state` in `collect_pr_context.py`) to verify reverted/untouched files, already-applied ````suggestion``` blocks, and post-comment line edits automatically.

### Fixed
- **VS Code `agy --hub` Agent Auto-Dispatch Discovery**:
  - Updated `discoverAntigravityLsEnv` (`extension/extension.js`) and `discover_ls_env` (`plugin/sidecars/quasar-web/server.py`) to discover VS Code's `agy --hub` processes (`--csrf_token=...`, `--hub-port=...`, and `--add-dir=...` per-workspace routing) in addition to standalone `language_server` processes.
- **Top-Level Review Comment Scoop-Up & Inline Action Bar Placement**:
  - `build_combined_top_level_comment` and `sync_top_level_comments_file` now exclude `github_existing` and non-`staged` threads so existing GitHub comments on files outside the current diff are never merged into new top-level review drafts.
  - Inline solution options and fix controls on `github_existing` threads now attach to Quasar's follow-up message rather than the reviewer's original GitHub comment, showing `✅ No Code Changes Needed` on already-addressed comments.

## [1.2.4] - 2026-11-09

### Added
- **New general-purpose review lenses**: `review-security`, `review-performance`, `review-concurrency`, `review-compat`, `review-error-handling`, `review-docs`, `review-readability`, `review-dependencies`, `review-accessibility`, and opt-in `review-newcomer`. Each declares default effort levels (`quasarEfforts`) and an applicability gate (`quasarAppliesWhen`) so irrelevant lenses skip diffs they don't apply to.
- **Configurable lenses per effort level**: `Quasar: Configure Review Lenses per Effort Level...` (sidebar, Preferences menu, Command Palette) and `review_lenses.py` CLI. Overrides persist as `lensEfforts` in `preferences.json`; `pr_context.json` now includes `review_lenses` (current effort) and `effort_lenses` (all levels), and the review pipeline spawns only the configured lenses.
- **Solution options on user-owned reviews**: findings and existing comments with multiple valid fixes carry selectable `solutionOptions` in all Quasar UIs, and fixes follow the chosen approach.

### Changed
- `medium` effort now includes `review-security` by default (gated to security-relevant diffs).
- Removed the built-in domain-specific lens from the shipped plugin; Quasar's built-in lenses are now general-purpose. Domain lenses belong in `~/.gemini/config/agents/` or `<repo>/.gemini/agents/`.

## [1.2.3] - 2026-10-30

### Added
- **Proxied & Remote Sandbox Support for GitHub Token Verification & Review Publishing**:
  - `submitToken()` in `quasar-web` now verifies GitHub Personal Access Tokens against `https://api.github.com/user` directly from the browser first and sends the verified `login` and `name` to `/api/github-token` (with graceful `RemoteDisconnected` fallback on the backend when outbound DLP proxies drop `ghp_...` / `github_pat_...` headers).
  - `post_pending_review.py` and `/api/publish-github` now return a hunk-aligned `needs_browser_publish` (`clientSidePublish: true`) payload when backend `POST` requests to `api.github.com` are blocked by outbound proxies (`RemoteDisconnected`), allowing the browser to `POST` the review directly to GitHub via CORS.
  - Added clean simulated review publishing in **Tutorial Sandbox** mode (`status: "tutorial_simulated"`).

### Fixed
- **Public PR Fetching Behind DLP Header Scanners**:
  - `github_api_get()` and `fetch_raw_file_content()` in `collect_pr_context.py` automatically retry without the `Authorization` header if a backend `GET` request carrying a stored token is dropped by an outbound proxy.
- **Sidecar Port Contention in `install.sh`**:
  - `install.sh` now skips launching `--standalone-daemon` when `SidecarManager` is active so they do not race for port `49341`.

## [1.2.2] - 2026-10-30

### Added
- **Quasar Web UI Sidecar & Standalone Browser App (`quasar-web`)**:
  - Added `plugin/sidecars/quasar-web` (`sidecar://quasar/quasar-web/` and `http://127.0.0.1:49341`) plus self-contained `quasar_review.html` export for Antigravity Web, Desktop Aux/Full Panes, and standalone browser sessions.
  - Supports interactive Study Guides, clickable SVG flowcharts, side-by-side & unified diffs, inline line Q&A, comment revision with the agent, batch comment fixing, and 1-click GitHub review publishing.
  - Added a **Live Agent Activity & Progress Indicator** (`#agentPill` & `#agentActivityBanner`) that tracks pipeline phases (`Phase 1/3` → `Phase 2/3` → `Phase 3/3`), active subagents, live tool steps, and elapsed time in real time.
- **Update Existing Pending Reviews on GitHub**:
  - Automatically detects and replaces any existing `PENDING` review owned by you on the PR when pushing updated staged comments (`delete_existing_pending_reviews` in `post_pending_review.py`).
- **New Quasar App & Activity Bar Icons**:
  - Added custom Quasar extension icon (`media/quasar-icon.png`), activity bar SVG (`media/review-icon.svg`), and Web UI favicon.

### Fixed
- **Top-Level PR Comment Preservation on Pending Reviews**:
  - Automatically copies the top-level review summary (`TOP_LEVEL_PR_COMMENTS.md`) to the clipboard when creating/updating a GitHub `PENDING` review (since GitHub discards `PENDING` review bodies in the web submit box) and fixed duplicate intro lines in `overflow_notes`.
- **Antigravity Web Sidecar Auth & AgentAPI Context Resolution**:
  - Added `/preload.js`, `X-Sidecar-Token` forwarding, cross-project `ANTIGRAVITY_PROJECT_ID` / `rootConversationId` resolution in `server.py`, and automatic plugin enablement (`JetboxWriteState` + `GetAllPlugins`) in `install.sh`.

## [1.2.0] - 2026-10-29

### Added
- **Interactive Sandbox PR Tutorial (`quasar.startTutorial`)**:
  - Added a zero-setup **🎓 Interactive Tutorial (Sandbox PR)** (`collect_pr_context.py --tutorial`) accessible from the Quasar Quick Menu, Command Palette, and empty-state welcome view.
  - Creates a realistic 3-file sandbox PR (`src/token_cache.py`, `src/auth_middleware.py`, `tests/test_token_cache.py`) with an interactive 5-step walkthrough banner in the Study Guide, clickable SVG architecture flowchart, guided reading tour stops, and realistic `🔴 Blocking`, `🟡 Design`, `🟢 Nit`, and `🤔 Uncertain` threads to test every Quasar feature safely.
- **Comments-Only Review Mode (`--comments-only`)**:
  - Added a **💬 Comments Only (Skip Study Guide & Tour)** scope selector when starting any GitHub PR or local branch review (as well as `--comments-only` in `collect_pr_context.py` and `publish_review_session.py`, plus `"commentsOnly"` in `SKILL.md`).
  - Skips generating the CliffsNotes study guide, Mermaid flowcharts, and reading tour chapters/stops—producing only high-signal inline review comments ready to publish to GitHub or fix with the agent.
- **Comment on Quasar Comments to Revise with Agent (`quasar.commentOnComment`)**:
  - Added **💬 Ask Agent to Change Comment...** across inline diff comment threads (both typing directly in the reply box and via thread action buttons), sidebar comment context menus, and Study Guide finding cards (`answer_comment_question.py --revise-finding`).
  - Instructs the agent to rewrite the comment's `title`, `body`, `suggestion`, or `severity` in-place based on your feedback and records a before/after phrasing example in your learned preferences.

### Changed
- **Concise-by-Default Comment Style & Optional Code Suggestions**:
  - Tuned `SKILL.md`, all 4 review subagents (`review-architect`, `review-bug-hunter`, `review-test-critic`, `review-advocate`), and default style preferences in `manage_preferences.py` so comments lead with the core issue in 1–3 concise sentences without filler.
  - Made `suggestion` blocks optional—only included when a concrete replacement snippet adds clear value over stating the issue plainly.
- **Cleaner Sidebar by Default (`quasar.toggleChecksTree`)**:
  - Hid the **Checks & Learned Preferences** sidebar section (`quasar.checksTree`) by default so the sidebar stays focused on **CliffsNotes & Reading Tour** and **Review Comments & Cart**, with a **Show / Hide Checks & Learned Preferences Panel** toggle in the Quasar Quick Menu and Command Palette.

### Fixed
- **Strict Per-Window Session Isolation**:
  - Locked each active review session to the exact VS Code / Antigravity window that activated it using per-window `windowId` (`vscode.env.sessionId`) and extension host `windowPid` (`process.pid`) ownership verification, plus window focus registration (`windows.json`).
  - Removed parent `.git` monorepo walk-up and open-document fallback in `resolveWorkspaceRootSync` / `resolve_workspace_root`, preventing reviews or tutorials in one window from ever leaking into other open windows.

## [1.1.2] - 2026-10-28

### Fixed
- **Conversation Routing for Review Actions (`Fix`, `Ask Quasar`, `Calibrate`)**:
  - Pinned the review session's owning `conversationId` in `active_session.json` (`publish_review_session.py` & `detectActiveConversationId`) so follow-up actions always route to the exact conversation that ran the review instead of another recent conversation tab in the workspace.
  - Tightened workspace path boundary matching when scanning conversation transcripts.
- **Effort Selector UI Polish**:
  - Fixed `$(pulse)` codicon rendering for Medium Effort in QuickPick, normalized sidebar `ThemeIcon` IDs, and added `timeEstimate` labels in the sidebar tree.

## [1.1.1] - 2026-10-28

### Added
- **Configurable Review Effort Levels (`Low`, `Medium`, `High`)**:
  - **⚡ Low Effort (Fast Single-Pass)**: Zero subagents, direct single-pass diff synthesis using `flash` for fast CliffsNotes tours and obvious high-confidence blockers (~20–35s).
  - **⚖️ Medium Effort (Balanced — Default)**: Spawns 2 parallel `flash` subagents (`review-architect` + `review-bug-hunter`) in a single wave and filters directly without a second sequential subagent wave (~45–75s).
  - **🔬 High Effort (Deep 4-Lens Pipeline)**: Runs the full parallel 3-subagent wave (`review-architect`, `review-bug-hunter`, `review-test-critic`) plus thorough false-positive verification for complex PRs.
  - Added quick-pick effort selector when launching PR or local branch reviews, a `Quasar: Set Review Effort Level (Low / Medium / High)...` command (`quasar.selectEffortLevel`), sidebar/header effort badges, and persistent `defaultEffort` preference in `~/.gemini/quasar/preferences.json`.

### Changed
- **Single-Column Study Guide View**:
  - Opening the Interactive CliffsNotes Study Guide now opens in the current active editor column (`vscode.ViewColumn.Active`) instead of forcing a side-by-side split window (`vscode.ViewColumn.Beside`).

## [0.1.0] - Initial Release

### Added
- **Interactive CliffsNotes Study Guide**:
  - Concise 1-sentence plain-English explanations by default with expandable `<details>` drawers for deeper context, invariants, and live line-numbered code snippets.
  - Built-in zero-dependency SVG Flowchart engine (`mermaid-preview.js`) with clickable nodes that jump directly to the relevant diff hunk.
  - Chapter & Tour Stop reading progress tracker (`✓ Read` checkboxes, progress ring, and `Next Unread Stop` navigation).
- **Multi-Lens Parallel Code Review Pipeline**:
  - 4 specialist subagents (`review-architect`, `review-bug-hunter`, `review-test-critic`, `review-advocate`) for high-signal, false-positive-filtered code review.
- **Native IDE Diff & Inline Comment Experience**:
  - Side-by-side diffs (`vscode.diff`) backed by clean local `base/` and `head/` file snapshots.
  - CliffsNotes Hover Cards & CodeLenses on changed hunks.
  - Inline `Ask Quasar` comment threads on any line of code.
  - Review findings staged by default for 1-click GitHub Review publishing (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`, or `PENDING`) and easily removable/dismissable.
- **Preference Calibration & Continuous Learning**:
  - Interactive calibration for uncertain/borderline findings (`status: "uncertain"`).
  - Non-destructive 3-layer preference hierarchy (Core Defaults, Imported Seed Skills, and Learned Preferences) persisted to `~/.gemini/quasar/PREFERENCES.md`.
- **Author Self-Review & Branch Switching**:
  - Auto-detects when a reviewed GitHub PR belongs to the current user (`gh`, `GITHUB_TOKEN`, git remotes, or git author identity) and prompts to switch to the PR branch.
  - 1-click `Fix Selected Comments with Agent` workflow for addressing review findings and teammate PR comments directly in the working tree.
- **Session Management**:
  - Per-window isolated review sessions, `Past Reviews` history archive & switcher, and `Close / Clear Current Review` to cleanly remove all review UI and inline comment decorations.
