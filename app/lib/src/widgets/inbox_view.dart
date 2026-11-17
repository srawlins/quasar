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

  Future<void> _showSettingsDialog(BuildContext context) async {
    final InboxSettings cfg = inbox.settings;
    String mode = cfg.mode;
    String effort = cfg.effort;
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
    bool watchReq = cfg.watchReviewRequested;
    bool watchAuth = cfg.watchAuthoredPrs;
    bool restrictRepos = cfg.restrictToWatchedRepos;
    bool includeDrafts = cfg.includeDrafts;
    bool commentsOnly = cfg.commentsOnly;

    final bool? saved = await showDialog<bool>(
      context: context,
      builder: (BuildContext ctx) => StatefulBuilder(
        builder: (BuildContext ctx, StateSetter setModal) => AlertDialog(
          title: const Text('⚙️ PR Inbox & Background Auto-Review Settings'),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  const Text(
                    'Configure trigger scope, cadence, and token caps so large queues trickle safely one PR at a time.',
                    style: TextStyle(fontSize: 12.5, color: Color(0xFF8B949E)),
                  ),
                  const SizedBox(height: 14),
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
                  const SizedBox(height: 12),
                  TextField(
                    controller: reposCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Watched Repos (optional owner/repo, ...)',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 8),
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: watchReq,
                    onChanged: (bool? v) =>
                        setModal(() => watchReq = v ?? true),
                    title: const Text(
                      'Watch PRs requesting my review (review-requested:@me)',
                      style: TextStyle(fontSize: 12.5),
                    ),
                  ),
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: watchAuth,
                    onChanged: (bool? v) =>
                        setModal(() => watchAuth = v ?? true),
                    title: const Text(
                      'Watch my open PRs with new comments / changes requested',
                      style: TextStyle(fontSize: 12.5),
                    ),
                  ),
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: restrictRepos,
                    onChanged: (bool? v) =>
                        setModal(() => restrictRepos = v ?? false),
                    title: const Text(
                      'Restrict @me queue only to Watched Repos above',
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
      'pollIntervalMinutes': int.tryParse(pollCtrl.text.trim()) ?? 15,
      'maxReviewsPerCycle': int.tryParse(maxCycleCtrl.text.trim()) ?? 1,
      'maxReviewsPerDay': int.tryParse(maxDayCtrl.text.trim()) ?? 6,
      'maxConcurrency': int.tryParse(concCtrl.text.trim()) ?? 1,
      'onlyUpdatedWithinDays': int.tryParse(recencyCtrl.text.trim()) ?? 14,
      'watchedRepos': reposCtrl.text.trim(),
      'watchReviewRequested': watchReq,
      'watchAuthoredPrs': watchAuth,
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
                          'Settings & Token Caps',
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
                                    '@${it.author} • +${it.additions}/-${it.deletions} (${it.changedFilesCount} files)',
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
