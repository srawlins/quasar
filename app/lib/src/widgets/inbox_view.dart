import 'package:flutter/material.dart';
import '../models/quasar_models.dart';

class InboxView extends StatelessWidget {
  const InboxView({
    super.key,
    required this.inbox,
    required this.onSyncNow,
    required this.onToggleDaemon,
    required this.onSaveSettings,
    required this.onActivateItem,
    required this.onPrecomputeItem,
    required this.onItemAction,
  });

  final InboxPayload inbox;
  final VoidCallback onSyncNow;
  final ValueChanged<bool> onToggleDaemon;
  final ValueChanged<Map<String, dynamic>> onSaveSettings;
  final ValueChanged<InboxItem> onActivateItem;
  final ValueChanged<InboxItem> onPrecomputeItem;
  final void Function(InboxItem item, String action) onItemAction;

  Widget _buildScopeRow({
    required String label,
    required bool watchValue,
    required bool autoValue,
    required ValueChanged<bool> onWatchChanged,
    required ValueChanged<bool> onAutoChanged,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontSize: 12.2, color: Color(0xFFE6EDF3)),
            ),
          ),
          SizedBox(
            width: 68,
            child: Center(
              child: Checkbox(
                visualDensity: VisualDensity.compact,
                value: watchValue,
                onChanged: (bool? v) => onWatchChanged(v ?? false),
              ),
            ),
          ),
          SizedBox(
            width: 86,
            child: Center(
              child: Checkbox(
                visualDensity: VisualDensity.compact,
                value: autoValue,
                onChanged: (bool? v) => onAutoChanged(v ?? false),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _showSettingsDialog(BuildContext context) async {
    final InboxSettings cfg = inbox.settings;
    String mode = cfg.mode;
    String effort = cfg.effort;
    String authoredPrMode =
        cfg.authoredPrMode == 'all_open' ? 'all_open' : 'feedback_only';
    final TextEditingController pollCtrl =
        TextEditingController(text: '${cfg.pollIntervalMinutes}');
    final TextEditingController maxCycleCtrl =
        TextEditingController(text: '${cfg.maxReviewsPerCycle}');
    final TextEditingController maxDayCtrl =
        TextEditingController(text: '${cfg.maxReviewsPerDay}');
    final TextEditingController concCtrl =
        TextEditingController(text: '${cfg.maxConcurrency}');
    final TextEditingController recencyCtrl =
        TextEditingController(text: '${cfg.onlyUpdatedWithinDays}');
    final TextEditingController reposCtrl =
        TextEditingController(text: cfg.watchedRepos.join(', '));
    final TextEditingController customQueryCtrl =
        TextEditingController(text: cfg.customQuery);
    final TextEditingController extraFlagsCtrl =
        TextEditingController(text: cfg.extraSearchFlags);
    bool watchReq = cfg.watchReviewRequested;
    bool autoReq = cfg.autoReviewReviewRequested;
    bool watchRevBy = cfg.watchReviewedBy;
    bool autoRevBy = cfg.autoReviewReviewedBy;
    bool watchComm = cfg.watchCommented;
    bool autoComm = cfg.autoReviewCommented;
    bool watchMent = cfg.watchMentioned;
    bool autoMent = cfg.autoReviewMentioned;
    bool watchAuth = cfg.watchAuthoredPrs;
    bool autoAuth = cfg.autoReviewAuthoredPrs;
    bool watchRepos = cfg.watchWatchedRepos;
    bool autoRepos = cfg.autoReviewWatchedRepos;
    bool watchCustom = cfg.watchCustomQuery;
    bool autoCustom = cfg.autoReviewCustomQuery;
    bool restrictRepos = cfg.restrictToWatchedRepos;
    bool includeDrafts = cfg.includeDrafts;
    bool commentsOnly = cfg.commentsOnly;

    final bool? saved = await showDialog<bool>(
      context: context,
      builder: (BuildContext ctx) => StatefulBuilder(
        builder: (BuildContext ctx, StateSetter setModal) => AlertDialog(
          title: const Text('⚙️ PR Inbox & Background Auto-Review Settings'),
          content: SizedBox(
            width: 580,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  const Text(
                    'Choose separately which PR flags sync into your Inbox (0 tokens) vs. which subset automatically runs background reviews.',
                    style: TextStyle(fontSize: 12.5, color: Color(0xFF8B949E)),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFF0D1117),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xFF30363D)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        const Row(
                          children: <Widget>[
                            Expanded(
                              child: Text(
                                'GITHUB PR SOURCE / FLAG',
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700,
                                  color: Color(0xFF8B949E),
                                ),
                              ),
                            ),
                            SizedBox(
                              width: 68,
                              child: Text(
                                '📥 Inbox',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700,
                                  color: Color(0xFF8B949E),
                                ),
                              ),
                            ),
                            SizedBox(
                              width: 86,
                              child: Text(
                                '⚡ Auto-Review',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700,
                                  color: Color(0xFF58A6FF),
                                ),
                              ),
                            ),
                          ],
                        ),
                        const Divider(height: 12, color: Color(0xFF30363D)),
                        _buildScopeRow(
                          label:
                              'Requesting my review (review-requested:@me)',
                          watchValue: watchReq,
                          autoValue: autoReq,
                          onWatchChanged: (bool v) => setModal(() {
                            watchReq = v;
                            if (!v) autoReq = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoReq = v;
                            if (v) watchReq = true;
                          }),
                        ),
                        _buildScopeRow(
                          label:
                              'Previously reviewed by me (reviewed-by:@me)',
                          watchValue: watchRevBy,
                          autoValue: autoRevBy,
                          onWatchChanged: (bool v) => setModal(() {
                            watchRevBy = v;
                            if (!v) autoRevBy = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoRevBy = v;
                            if (v) watchRevBy = true;
                          }),
                        ),
                        _buildScopeRow(
                          label: 'Commented on by me (commenter:@me)',
                          watchValue: watchComm,
                          autoValue: autoComm,
                          onWatchChanged: (bool v) => setModal(() {
                            watchComm = v;
                            if (!v) autoComm = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoComm = v;
                            if (v) watchComm = true;
                          }),
                        ),
                        _buildScopeRow(
                          label:
                              'Mentioning / assigned to me (mentions:@me, assignee:@me)',
                          watchValue: watchMent,
                          autoValue: autoMent,
                          onWatchChanged: (bool v) => setModal(() {
                            watchMent = v;
                            if (!v) autoMent = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoMent = v;
                            if (v) watchMent = true;
                          }),
                        ),
                        _buildScopeRow(
                          label: 'My own open PRs (author:@me)',
                          watchValue: watchAuth,
                          autoValue: autoAuth,
                          onWatchChanged: (bool v) => setModal(() {
                            watchAuth = v;
                            if (!v) autoAuth = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoAuth = v;
                            if (v) watchAuth = true;
                          }),
                        ),
                        _buildScopeRow(
                          label:
                              'Watched repositories below (when not restrict-only)',
                          watchValue: watchRepos,
                          autoValue: autoRepos,
                          onWatchChanged: (bool v) => setModal(() {
                            watchRepos = v;
                            if (!v) autoRepos = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoRepos = v;
                            if (v) watchRepos = true;
                          }),
                        ),
                        _buildScopeRow(
                          label: 'Custom GitHub search query below',
                          watchValue: watchCustom,
                          autoValue: autoCustom,
                          onWatchChanged: (bool v) => setModal(() {
                            watchCustom = v;
                            if (!v) autoCustom = false;
                          }),
                          onAutoChanged: (bool v) => setModal(() {
                            autoCustom = v;
                            if (v) watchCustom = true;
                          }),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: authoredPrMode,
                    decoration: const InputDecoration(
                      labelText: 'My Own PRs (author:@me) Trigger Mode',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                    items: const <DropdownMenuItem<String>>[
                      DropdownMenuItem<String>(
                        value: 'feedback_only',
                        child: Text(
                          'Only when external comments / reviews exist',
                        ),
                      ),
                      DropdownMenuItem<String>(
                        value: 'all_open',
                        child: Text('All my open PRs (self-review on push)'),
                      ),
                    ],
                    onChanged: (String? v) =>
                        setModal(() => authoredPrMode = v ?? 'feedback_only'),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: customQueryCtrl,
                    decoration: const InputDecoration(
                      labelText:
                          'Custom GitHub Search Query (optional — supports @me)',
                      hintText:
                          'e.g. repo:acme/backend label:security -label:wip',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: extraFlagsCtrl,
                    decoration: const InputDecoration(
                      labelText:
                          'Extra GitHub Search Flags Applied to All Queries (optional)',
                      hintText:
                          'e.g. -label:do-not-merge -author:app/dependabot',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: reposCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Watched Repos (optional owner/repo, ...)',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          initialValue: mode,
                          decoration: const InputDecoration(
                            labelText: 'Watcher Mode',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                          items: const <DropdownMenuItem<String>>[
                            DropdownMenuItem<String>(
                              value: 'auto_precompute',
                              child: Text('Auto-Precompute'),
                            ),
                            DropdownMenuItem<String>(
                              value: 'sync_queue_only',
                              child: Text('Sync Only (0 Tokens)'),
                            ),
                          ],
                          onChanged: (String? v) =>
                              setModal(() => mode = v ?? 'auto_precompute'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: DropdownButtonFormField<String>(
                          initialValue: effort,
                          decoration: const InputDecoration(
                            labelText: 'Background Effort',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                          items: const <DropdownMenuItem<String>>[
                            DropdownMenuItem<String>(
                              value: 'high',
                              child: Text('High (Deep)'),
                            ),
                            DropdownMenuItem<String>(
                              value: 'medium',
                              child: Text('Medium'),
                            ),
                            DropdownMenuItem<String>(
                              value: 'low',
                              child: Text('Low'),
                            ),
                          ],
                          onChanged: (String? v) =>
                              setModal(() => effort = v ?? 'high'),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: TextField(
                          controller: pollCtrl,
                          decoration: const InputDecoration(
                            labelText: 'Poll (min)',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          controller: maxCycleCtrl,
                          decoration: const InputDecoration(
                            labelText: 'Max / Cycle',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          controller: maxDayCtrl,
                          decoration: const InputDecoration(
                            labelText: 'Daily Cap (0=∞)',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: TextField(
                          controller: concCtrl,
                          decoration: const InputDecoration(
                            labelText: 'Max Concurrency',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: TextField(
                          controller: recencyCtrl,
                          decoration: const InputDecoration(
                            labelText: 'Recency Cutoff (days)',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: restrictRepos,
                    onChanged: (bool? v) =>
                        setModal(() => restrictRepos = v ?? false),
                    title: const Text(
                      'Restrict @me queries only to Watched Repos above',
                      style: TextStyle(fontSize: 12.5),
                    ),
                  ),
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: includeDrafts,
                    onChanged: (bool? v) =>
                        setModal(() => includeDrafts = v ?? false),
                    title: const Text(
                      'Include Draft PRs',
                      style: TextStyle(fontSize: 12.5),
                    ),
                  ),
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: commentsOnly,
                    onChanged: (bool? v) =>
                        setModal(() => commentsOnly = v ?? false),
                    title: const Text(
                      'Comments-Only format (skip Study Guide & Tour)',
                      style: TextStyle(fontSize: 12.5),
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Save Settings'),
            ),
          ],
        ),
      ),
    );

    final Map<String, dynamic> payload = <String, dynamic>{
      'mode': mode,
      'effort': effort,
      'authoredPrMode': authoredPrMode,
      'pollIntervalMinutes': int.tryParse(pollCtrl.text.trim()) ?? 15,
      'maxReviewsPerCycle': int.tryParse(maxCycleCtrl.text.trim()) ?? 1,
      'maxReviewsPerDay': int.tryParse(maxDayCtrl.text.trim()) ?? 6,
      'maxConcurrency': int.tryParse(concCtrl.text.trim()) ?? 1,
      'onlyUpdatedWithinDays': int.tryParse(recencyCtrl.text.trim()) ?? 14,
      'watchedRepos': reposCtrl.text.trim(),
      'customQuery': customQueryCtrl.text.trim(),
      'extraSearchFlags': extraFlagsCtrl.text.trim(),
      'watchReviewRequested': watchReq,
      'autoReviewReviewRequested': autoReq,
      'watchReviewedBy': watchRevBy,
      'autoReviewReviewedBy': autoRevBy,
      'watchCommented': watchComm,
      'autoReviewCommented': autoComm,
      'watchMentioned': watchMent,
      'autoReviewMentioned': autoMent,
      'watchAuthoredPrs': watchAuth,
      'autoReviewAuthoredPrs': autoAuth,
      'watchWatchedRepos': watchRepos,
      'autoReviewWatchedRepos': autoRepos,
      'watchCustomQuery': watchCustom,
      'autoReviewCustomQuery': autoCustom,
      'restrictToWatchedRepos': restrictRepos,
      'includeDrafts': includeDrafts,
      'commentsOnly': commentsOnly,
    };
    pollCtrl.dispose();
    maxCycleCtrl.dispose();
    maxDayCtrl.dispose();
    concCtrl.dispose();
    recencyCtrl.dispose();
    reposCtrl.dispose();
    customQueryCtrl.dispose();
    extraFlagsCtrl.dispose();

    if (saved == true) {
      onSaveSettings(payload);
    }
  }

  @override
  Widget build(BuildContext context) {
    final InboxSettings cfg = inbox.settings;
    final String dayCap = inbox.maxReviewsPerDay > 0
        ? '${inbox.reviewsRunToday}/${inbox.maxReviewsPerDay} today'
        : '${inbox.reviewsRunToday} today (∞)';
    final List<String> autoActiveLabels = <String>[
      if (cfg.autoReviewReviewRequested && cfg.watchReviewRequested) 'Requested',
      if (cfg.autoReviewReviewedBy && cfg.watchReviewedBy) 'Reviewed',
      if (cfg.autoReviewCommented && cfg.watchCommented) 'Commented',
      if (cfg.autoReviewMentioned && cfg.watchMentioned) 'Mentioned',
      if (cfg.autoReviewAuthoredPrs && cfg.watchAuthoredPrs) 'My PRs',
      if (cfg.autoReviewWatchedRepos &&
          cfg.watchWatchedRepos &&
          cfg.watchedRepos.isNotEmpty)
        'Watched Repos',
      if (cfg.autoReviewCustomQuery &&
          cfg.watchCustomQuery &&
          cfg.customQuery.trim().isNotEmpty)
        'Custom Query',
    ];
    final String autoSummary = cfg.mode == 'sync_queue_only'
        ? 'Off (Sync Only)'
        : (autoActiveLabels.isEmpty ? 'None' : autoActiveLabels.join(' + '));

    const List<({String key, String label, Color color})> groups =
        <({String key, String label, Color color})>[
      (
        key: 'in_progress',
        label: '⏳ PRE-REVIEWING IN BACKGROUND',
        color: Color(0xFF58A6FF),
      ),
      (
        key: 'ready_to_review',
        label: '🟢 READY TO REVIEW (0-SECOND OPEN)',
        color: Color(0xFF3FB950),
      ),
      (
        key: 'author_action_needed',
        label: '🛠️ YOUR PRS — ACTION NEEDED (0-SECOND OPEN)',
        color: Color(0xFFD29922),
      ),
      (
        key: 'quarantined',
        label: '🚨 QUARANTINED BY SECURITY GATE',
        color: Color(0xFFF85149),
      ),
      (
        key: 'queued',
        label: '📋 QUEUED IN GITHUB (NOT PRE-REVIEWED YET)',
        color: Color(0xFFE6EDF3),
      ),
      (
        key: 'waiting',
        label: '⏸️ WAITING ON AUTHOR / REVIEWERS',
        color: Color(0xFF8B949E),
      ),
      (
        key: 'deleted',
        label: '🗑️ DELETED REVIEWS (RE-QUEUE OR RE-REVIEW)',
        color: Color(0xFF8B949E),
      ),
    ];

    return ListView(
      padding: const EdgeInsets.all(20),
      children: <Widget>[
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF161B22),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: const Color(0xFF30363D)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Wrap(
                spacing: 10,
                runSpacing: 8,
                alignment: WrapAlignment.spaceBetween,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: <Widget>[
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        '📥 Multi-PR Inbox & Background Auto-Review',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: Color(0xFFE6EDF3),
                        ),
                      ),
                      SizedBox(height: 3),
                      Text(
                        'Pre-computes CliffsNotes & findings in isolated storage so reviews open in 0s without interrupting active work.',
                        style: TextStyle(
                          fontSize: 12,
                          color: Color(0xFF8B949E),
                        ),
                      ),
                    ],
                  ),
                  Wrap(
                    spacing: 8,
                    runSpacing: 6,
                    children: <Widget>[
                      FilledButton.icon(
                        onPressed: () => onToggleDaemon(!inbox.daemonRunning),
                        icon: Icon(
                          inbox.daemonRunning ? Icons.pause : Icons.play_arrow,
                          size: 16,
                        ),
                        label: Text(
                          inbox.daemonRunning
                              ? 'Pause Auto-Review'
                              : 'Enable Auto-Review',
                          style: const TextStyle(fontSize: 12),
                        ),
                      ),
                      OutlinedButton.icon(
                        onPressed: onSyncNow,
                        icon: const Icon(Icons.sync, size: 15),
                        label: const Text(
                          'Sync Queue (0 Tokens)',
                          style: TextStyle(fontSize: 12),
                        ),
                      ),
                      OutlinedButton.icon(
                        onPressed: () => _showSettingsDialog(context),
                        icon: const Icon(Icons.settings_outlined, size: 15),
                        label: const Text(
                          'Settings & Auto-Review Flags',
                          style: TextStyle(fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: <Widget>[
                  _MetaChip(
                    text: inbox.daemonRunning
                        ? '● Daemon Active (PID ${inbox.daemonPid ?? ''})'
                        : '○ Daemon Paused',
                    highlight: inbox.daemonRunning,
                  ),
                  _MetaChip(
                    text: cfg.mode == 'sync_queue_only'
                        ? 'Mode: Sync Only (0 Tokens)'
                        : 'Mode: ${cfg.effort.toUpperCase()} Precompute',
                  ),
                  _MetaChip(text: 'Auto-Review: $autoSummary'),
                  _MetaChip(text: 'Every ${cfg.pollIntervalMinutes}m'),
                  _MetaChip(text: 'Max ${cfg.maxReviewsPerCycle}/cycle'),
                  _MetaChip(text: 'Daily Cap: $dayCap'),
                  _MetaChip(text: 'Concurrency: ${cfg.maxConcurrency}'),
                ],
              ),
              if (inbox.lastSyncError.isNotEmpty) ...<Widget>[
                const SizedBox(height: 10),
                Text(
                  '⚠️ ${inbox.lastSyncError}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFFE3B341),
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 14),
        if (inbox.items.isEmpty)
          Container(
            padding: const EdgeInsets.all(28),
            decoration: BoxDecoration(
              color: const Color(0xFF161B22),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFF30363D)),
            ),
            child: const Center(
              child: Text(
                'No open PRs in your Inbox yet. Click "Sync Queue (0 Tokens)" to fetch your GitHub queue, or "Settings & Token Caps" to customize.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12.5, color: Color(0xFF8B949E)),
              ),
            ),
          ),
        for (final ({String key, String label, Color color}) g in groups) ...<Widget>[
          Builder(
            builder: (BuildContext ctx) {
              final List<InboxItem> gItems = inbox.items
                  .where((InboxItem it) => it.inboxGroup == g.key)
                  .toList();
              if (gItems.isEmpty) {
                return const SizedBox.shrink();
              }
              return Container(
                margin: const EdgeInsets.only(bottom: 14),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF161B22),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFF30363D)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      '${g.label} (${gItems.length})',
                      style: TextStyle(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.5,
                        color: g.color,
                      ),
                    ),
                    const SizedBox(height: 8),
                    for (final InboxItem it in gItems)
                      Container(
                        margin: const EdgeInsets.only(top: 8),
                        padding: const EdgeInsets.all(11),
                        decoration: BoxDecoration(
                          color: const Color(0xFF0D1117),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFF21262D)),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: <Widget>[
                                  Text(
                                    '${it.unread ? '● ' : ''}${it.updatedSinceLastReview ? '🔄 ' : ''}${it.owner}/${it.repo}#${it.number}: ${it.title}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                      color: Color(0xFFE6EDF3),
                                    ),
                                  ),
                                  const SizedBox(height: 3),
                                  Text(
                                    <String>[
                                      '@${it.author}',
                                      if (it.roleLabel.isNotEmpty) it.roleLabel,
                                      if (it.headSha.isNotEmpty ||
                                          it.changedFilesCount > 0 ||
                                          it.additions > 0 ||
                                          it.deletions > 0)
                                        '+${it.additions}/-${it.deletions} (${it.changedFilesCount} files)',
                                    ].join(' • '),
                                    style: const TextStyle(
                                      fontFamily: 'monospace',
                                      fontSize: 11,
                                      color: Color(0xFF8B949E),
                                    ),
                                  ),
                                  if (it.tldr.isNotEmpty) ...<Widget>[
                                    const SizedBox(height: 4),
                                    Text(
                                      it.tldr,
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: Color(0xFFC9D1D9),
                                      ),
                                    ),
                                  ],
                                  if (it.skipReason.isNotEmpty) ...<Widget>[
                                    const SizedBox(height: 3),
                                    Text(
                                      it.skipReason,
                                      style: const TextStyle(
                                        fontSize: 11,
                                        color: Color(0xFFE3B341),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                            const SizedBox(width: 10),
                            Wrap(
                              spacing: 6,
                              runSpacing: 6,
                              children: <Widget>[
                                if (it.isReadyToOpen)
                                  FilledButton.tonal(
                                    onPressed: () => onActivateItem(it),
                                    child: const Text(
                                      '📖 Open in 0s',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ),
                                if (it.inboxGroup == 'queued')
                                  OutlinedButton(
                                    onPressed: () => onPrecomputeItem(it),
                                    child: const Text(
                                      '⚡ Pre-Review',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ),
                                if (it.inboxGroup == 'deleted') ...<Widget>[
                                  FilledButton.tonal(
                                    onPressed: () =>
                                        onItemAction(it, 'requeue'),
                                    child: const Text(
                                      '➕ Re-Add to Queue',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ),
                                  OutlinedButton(
                                    onPressed: () => onPrecomputeItem(it),
                                    child: const Text(
                                      '⚡ Re-Review Now',
                                      style: TextStyle(fontSize: 12),
                                    ),
                                  ),
                                ],
                                if (it.inboxGroup != 'deleted')
                                  IconButton(
                                    tooltip: 'Mark Reviewed',
                                    onPressed: () =>
                                        onItemAction(it, 'markReviewed'),
                                    icon: const Icon(Icons.check, size: 16),
                                  ),
                                IconButton(
                                  tooltip: 'Hide from Inbox',
                                  onPressed: () => onItemAction(it, 'dismiss'),
                                  icon: const Icon(Icons.close, size: 16),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              );
            },
          ),
        ],
      ],
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.text, this.highlight = false});

  final String text;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final Color c =
        highlight ? const Color(0xFF3FB950) : const Color(0xFF8B949E);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
      decoration: BoxDecoration(
        color: c.withValues(alpha: highlight ? 0.14 : 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: c.withValues(alpha: 0.4)),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 11.5,
          fontWeight: highlight ? FontWeight.w600 : FontWeight.w500,
          color: highlight ? const Color(0xFF56D364) : c,
        ),
      ),
    );
  }
}
