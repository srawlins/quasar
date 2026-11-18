class QuasarStatePayload {
  const QuasarStatePayload({
    required this.activeSession,
    required this.filesDiff,
    required this.sessions,
    required this.githubAuth,
    required this.defaultWorkspaceDir,
    required this.agentStatus,
    required this.sidecarPort,
    required this.inbox,
  });

  factory QuasarStatePayload.fromJson(Map<String, dynamic> json) {
    final Object? rawActive = json['activeSession'];
    final List<dynamic> rawDiffs =
        (json['filesDiff'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawSessions =
        (json['sessions'] as List<dynamic>?) ?? const <dynamic>[];
    final Map<String, dynamic> rawAuth =
        (json['githubAuth'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final Map<String, dynamic> rawAgent =
        (json['agentStatus'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final Map<String, dynamic> rawInbox =
        (json['inbox'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};

    return QuasarStatePayload(
      activeSession: rawActive is Map<String, dynamic>
          ? ReviewSession.fromJson(rawActive)
          : null,
      filesDiff: rawDiffs
          .whereType<Map<String, dynamic>>()
          .map(FileDiff.fromJson)
          .toList(),
      sessions: rawSessions
          .whereType<Map<String, dynamic>>()
          .map(SessionSummary.fromJson)
          .toList(),
      githubAuth: GithubAuthInfo.fromJson(rawAuth),
      defaultWorkspaceDir: '${json['defaultWorkspaceDir'] ?? ''}',
      agentStatus: AgentLiveStatus.fromJson(rawAgent),
      sidecarPort: (json['sidecarPort'] as num?)?.toInt() ?? 49341,
      inbox: InboxPayload.fromJson(rawInbox),
    );
  }

  final ReviewSession? activeSession;
  final List<FileDiff> filesDiff;
  final List<SessionSummary> sessions;
  final GithubAuthInfo githubAuth;
  final String defaultWorkspaceDir;
  final AgentLiveStatus agentStatus;
  final int sidecarPort;
  final InboxPayload inbox;
}

class InboxSettings {
  const InboxSettings({
    required this.enabled,
    required this.mode,
    required this.watchReviewRequested,
    this.watchReviewedBy = true,
    this.watchCommented = true,
    this.watchMentioned = true,
    required this.watchAuthoredPrs,
    this.watchWatchedRepos = true,
    this.watchCustomQuery = true,
    this.watchInvolvedPrs = true,
    this.autoReviewReviewRequested = true,
    this.autoReviewReviewedBy = false,
    this.autoReviewCommented = false,
    this.autoReviewMentioned = false,
    this.autoReviewAuthoredPrs = false,
    this.autoReviewWatchedRepos = false,
    this.autoReviewCustomQuery = false,
    this.authoredPrMode = 'feedback_only',
    this.customQuery = '',
    this.extraSearchFlags = '',
    required this.watchedRepos,
    required this.restrictToWatchedRepos,
    required this.includeDrafts,
    required this.effort,
    required this.commentsOnly,
    this.cliModel = '',
    this.cliFallbackModels = const <String>[],
    this.cliAgent = '',
    required this.pollIntervalMinutes,
    required this.maxConcurrency,
    required this.maxReviewsPerCycle,
    required this.maxReviewsPerDay,
    required this.onlyUpdatedWithinDays,
    required this.notifyWhenReady,
    this.notifyOnError = true,
    this.incrementalUpdates = true,
  });

  factory InboxSettings.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawRepos =
        (json['watchedRepos'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawFallbacks =
        (json['cliFallbackModels'] as List<dynamic>?) ?? const <dynamic>[];
    final bool legacyInvolved = json['watchInvolvedPrs'] != false;
    final bool watchReq = json['watchReviewRequested'] != false;
    final bool watchRevBy = json.containsKey('watchReviewedBy')
        ? json['watchReviewedBy'] == true
        : legacyInvolved;
    final bool watchComm = json.containsKey('watchCommented')
        ? json['watchCommented'] == true
        : legacyInvolved;
    final bool watchMent = json.containsKey('watchMentioned')
        ? json['watchMentioned'] == true
        : legacyInvolved;
    final bool watchAuth = json['watchAuthoredPrs'] != false;
    final bool watchRepos = json['watchWatchedRepos'] != false;
    final bool watchCustom = json['watchCustomQuery'] != false;
    return InboxSettings(
      enabled: json['enabled'] == true,
      mode: '${json['mode'] ?? 'auto_precompute'}',
      watchReviewRequested: watchReq,
      watchReviewedBy: watchRevBy,
      watchCommented: watchComm,
      watchMentioned: watchMent,
      watchAuthoredPrs: watchAuth,
      watchWatchedRepos: watchRepos,
      watchCustomQuery: watchCustom,
      watchInvolvedPrs: watchRevBy || watchComm || watchMent,
      autoReviewReviewRequested:
          watchReq && (json['autoReviewReviewRequested'] != false),
      autoReviewReviewedBy:
          watchRevBy && (json['autoReviewReviewedBy'] == true),
      autoReviewCommented: watchComm && (json['autoReviewCommented'] == true),
      autoReviewMentioned: watchMent && (json['autoReviewMentioned'] == true),
      autoReviewAuthoredPrs:
          watchAuth && (json['autoReviewAuthoredPrs'] == true),
      autoReviewWatchedRepos:
          watchRepos && (json['autoReviewWatchedRepos'] == true),
      autoReviewCustomQuery:
          watchCustom && (json['autoReviewCustomQuery'] == true),
      authoredPrMode: '${json['authoredPrMode'] ?? 'feedback_only'}',
      customQuery: '${json['customQuery'] ?? ''}',
      extraSearchFlags: '${json['extraSearchFlags'] ?? ''}',
      watchedRepos: rawRepos
          .map((dynamic e) => '$e'.trim())
          .where((String s) => s.isNotEmpty)
          .toList(),
      restrictToWatchedRepos: json['restrictToWatchedRepos'] == true,
      includeDrafts: json['includeDrafts'] == true,
      effort: '${json['effort'] ?? 'high'}',
      commentsOnly: json['commentsOnly'] == true,
      cliModel: '${json['cliModel'] ?? ''}',
      cliFallbackModels: rawFallbacks
          .map((dynamic e) => '$e'.trim())
          .where((String s) => s.isNotEmpty)
          .toList(),
      cliAgent: '${json['cliAgent'] ?? ''}',
      pollIntervalMinutes:
          (json['pollIntervalMinutes'] as num?)?.toInt() ?? 15,
      maxConcurrency: (json['maxConcurrency'] as num?)?.toInt() ?? 1,
      maxReviewsPerCycle: (json['maxReviewsPerCycle'] as num?)?.toInt() ?? 1,
      maxReviewsPerDay: (json['maxReviewsPerDay'] as num?)?.toInt() ?? 6,
      onlyUpdatedWithinDays:
          (json['onlyUpdatedWithinDays'] as num?)?.toInt() ?? 14,
      notifyWhenReady: json['notifyWhenReady'] != false,
      notifyOnError: json['notifyOnError'] != false,
      incrementalUpdates: json['incrementalUpdates'] != false,
    );
  }

  final bool enabled;
  final String mode;
  final bool watchReviewRequested;
  final bool watchReviewedBy;
  final bool watchCommented;
  final bool watchMentioned;
  final bool watchAuthoredPrs;
  final bool watchWatchedRepos;
  final bool watchCustomQuery;
  final bool watchInvolvedPrs;
  final bool autoReviewReviewRequested;
  final bool autoReviewReviewedBy;
  final bool autoReviewCommented;
  final bool autoReviewMentioned;
  final bool autoReviewAuthoredPrs;
  final bool autoReviewWatchedRepos;
  final bool autoReviewCustomQuery;
  final String authoredPrMode;
  final String customQuery;
  final String extraSearchFlags;
  final List<String> watchedRepos;
  final bool restrictToWatchedRepos;
  final bool includeDrafts;
  final String effort;
  final bool commentsOnly;
  final String cliModel;
  final List<String> cliFallbackModels;
  final String cliAgent;
  final int pollIntervalMinutes;
  final int maxConcurrency;
  final int maxReviewsPerCycle;
  final int maxReviewsPerDay;
  final int onlyUpdatedWithinDays;
  final bool notifyWhenReady;
  final bool notifyOnError;
  final bool incrementalUpdates;
}

class CliModelOption {
  const CliModelOption({required this.id, required this.label});

  factory CliModelOption.fromJson(Map<String, dynamic> json) {
    final String id = '${json['id'] ?? 'auto'}'.trim();
    final String lbl = '${json['label'] ?? id}'.trim();
    return CliModelOption(id: id.isEmpty ? 'auto' : id, label: lbl);
  }

  final String id;
  final String label;
}

class InboxItem {
  const InboxItem({
    required this.id,
    required this.owner,
    required this.repo,
    required this.number,
    required this.title,
    required this.url,
    required this.author,
    required this.role,
    this.roleLabel = '',
    required this.status,
    required this.inboxGroup,
    required this.additions,
    required this.deletions,
    required this.changedFilesCount,
    required this.findingsCount,
    required this.reviewCommentsCount,
    required this.changesRequested,
    required this.unread,
    required this.updatedSinceLastReview,
    required this.tldr,
    required this.skipReason,
    required this.lastError,
    this.lastErrorKind = '',
    this.headSha = '',
  });

  factory InboxItem.fromJson(Map<String, dynamic> json) {
    return InboxItem(
      id: '${json['id'] ?? ''}',
      owner: '${json['owner'] ?? ''}',
      repo: '${json['repo'] ?? ''}',
      number: (json['number'] as num?)?.toInt() ?? 0,
      title: '${json['title'] ?? ''}',
      url: '${json['url'] ?? ''}',
      author: '${json['author'] ?? ''}',
      role: '${json['role'] ?? 'reviewer'}',
      roleLabel: '${json['roleLabel'] ?? ''}',
      status: '${json['status'] ?? 'queued'}',
      inboxGroup: '${json['inboxGroup'] ?? 'queued'}',
      additions: (json['additions'] as num?)?.toInt() ?? 0,
      deletions: (json['deletions'] as num?)?.toInt() ?? 0,
      changedFilesCount: (json['changedFilesCount'] as num?)?.toInt() ?? 0,
      findingsCount: (json['findingsCount'] as num?)?.toInt() ?? 0,
      reviewCommentsCount:
          (json['reviewCommentsCount'] as num?)?.toInt() ?? 0,
      changesRequested: json['changesRequested'] == true,
      unread: json['unread'] == true,
      updatedSinceLastReview: json['updatedSinceLastReview'] == true,
      tldr: '${json['tldr'] ?? ''}',
      skipReason: '${json['skipReason'] ?? ''}',
      lastError: '${json['lastError'] ?? ''}',
      lastErrorKind: '${json['lastErrorKind'] ?? ''}',
      headSha: '${json['headSha'] ?? ''}',
    );
  }

  final String id;
  final String headSha;
  final String owner;
  final String repo;
  final int number;
  final String title;
  final String url;
  final String author;
  final String role;
  final String roleLabel;
  final String status;
  final String inboxGroup;
  final int additions;
  final int deletions;
  final int changedFilesCount;
  final int findingsCount;
  final int reviewCommentsCount;
  final bool changesRequested;
  final bool unread;
  final bool updatedSinceLastReview;
  final String tldr;
  final String skipReason;
  final String lastError;
  final String lastErrorKind;

  bool get isQuotaError =>
      lastErrorKind == 'quota_exhausted' ||
      lastError.toLowerCase().contains('quota') ||
      lastError.toLowerCase().contains('out of model');

  bool get isReadyToOpen => status == 'ready' || status == 'quarantined';
}

class InboxPayload {
  const InboxPayload({
    required this.settings,
    required this.daemonRunning,
    required this.daemonPid,
    required this.reviewsRunToday,
    required this.maxReviewsPerDay,
    required this.readyCount,
    required this.unreadReadyCount,
    this.errorCount = 0,
    this.quotaErrorCount = 0,
    required this.lastSyncError,
    required this.items,
    this.availableModels = const <CliModelOption>[],
    this.availableAgents = const <String>[],
  });

  factory InboxPayload.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> rawCfg =
        (json['settings'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final Map<String, dynamic> rawDaemon =
        (json['daemon'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final Map<String, dynamic> rawBudget =
        (json['budget'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final Map<String, dynamic> rawCounts =
        (json['counts'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final List<dynamic> rawItems =
        (json['items'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawModels =
        (json['availableModels'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawAgents =
        (json['availableAgents'] as List<dynamic>?) ?? const <dynamic>[];
    return InboxPayload(
      settings: InboxSettings.fromJson(rawCfg),
      daemonRunning: rawDaemon['running'] == true,
      daemonPid: (rawDaemon['pid'] as num?)?.toInt(),
      reviewsRunToday: (rawBudget['reviewsRunToday'] as num?)?.toInt() ?? 0,
      maxReviewsPerDay: (rawBudget['maxReviewsPerDay'] as num?)?.toInt() ?? 6,
      readyCount: (rawCounts['ready'] as num?)?.toInt() ?? 0,
      unreadReadyCount: (rawCounts['unreadReady'] as num?)?.toInt() ?? 0,
      errorCount: (rawCounts['errors'] as num?)?.toInt() ?? 0,
      quotaErrorCount: (rawCounts['quotaErrors'] as num?)?.toInt() ?? 0,
      lastSyncError: '${json['lastSyncError'] ?? ''}',
      items: rawItems
          .whereType<Map<String, dynamic>>()
          .map(InboxItem.fromJson)
          .toList(),
      availableModels: rawModels
          .whereType<Map<String, dynamic>>()
          .map(CliModelOption.fromJson)
          .toList(),
      availableAgents: rawAgents
          .map((dynamic e) => '$e'.trim())
          .where((String s) => s.isNotEmpty)
          .toList(),
    );
  }

  final InboxSettings settings;
  final bool daemonRunning;
  final int? daemonPid;
  final int reviewsRunToday;
  final int maxReviewsPerDay;
  final int readyCount;
  final int unreadReadyCount;
  final int errorCount;
  final int quotaErrorCount;
  final String lastSyncError;
  final List<InboxItem> items;
  final List<CliModelOption> availableModels;
  final List<String> availableAgents;
}

class SessionSummary {
  const SessionSummary({
    required this.id,
    required this.sessionId,
    required this.title,
    required this.repo,
    required this.updatedAt,
    required this.stopsRead,
    required this.stopsTotal,
    required this.threadsCount,
    required this.effortLevel,
    required this.commentsOnly,
    required this.isTutorial,
  });

  factory SessionSummary.fromJson(Map<String, dynamic> json) {
    return SessionSummary(
      id: '${json['id'] ?? ''}',
      sessionId: '${json['sessionId'] ?? json['id'] ?? ''}',
      title: '${json['title'] ?? 'Review Session'}',
      repo: '${json['repo'] ?? ''}',
      updatedAt: '${json['updatedAt'] ?? ''}',
      stopsRead: (json['stopsRead'] as num?)?.toInt() ?? 0,
      stopsTotal: (json['stopsTotal'] as num?)?.toInt() ?? 0,
      threadsCount: (json['threadsCount'] as num?)?.toInt() ?? 0,
      effortLevel: '${json['effortLevel'] ?? 'high'}',
      commentsOnly: json['commentsOnly'] == true,
      isTutorial: json['isTutorial'] == true,
    );
  }

  final String id;
  final String sessionId;
  final String title;
  final String repo;
  final String updatedAt;
  final int stopsRead;
  final int stopsTotal;
  final int threadsCount;
  final String effortLevel;
  final bool commentsOnly;
  final bool isTutorial;
}

class GithubAuthInfo {
  const GithubAuthInfo({
    required this.configured,
    required this.login,
    required this.tokenPreview,
  });

  factory GithubAuthInfo.fromJson(Map<String, dynamic> json) {
    return GithubAuthInfo(
      configured: json['configured'] == true,
      login: '${json['login'] ?? ''}',
      tokenPreview: '${json['tokenPreview'] ?? ''}',
    );
  }

  final bool configured;
  final String login;
  final String tokenPreview;
}

class AgentLiveStatus {
  const AgentLiveStatus({
    required this.active,
    required this.completedJustNow,
    required this.title,
    required this.stage,
    required this.detail,
    required this.percent,
    required this.elapsedSeconds,
    required this.subagents,
  });

  factory AgentLiveStatus.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawSubs =
        (json['subagents'] as List<dynamic>?) ?? const <dynamic>[];
    return AgentLiveStatus(
      active: json['active'] == true,
      completedJustNow: json['completedJustNow'] == true,
      title: '${json['title'] ?? ''}',
      stage: '${json['stage'] ?? ''}',
      detail: '${json['detail'] ?? ''}',
      percent: (json['percent'] as num?)?.toInt() ?? 0,
      elapsedSeconds: (json['elapsedSeconds'] as num?)?.toInt() ?? 0,
      subagents: rawSubs.map((dynamic e) => '$e').toList(),
    );
  }

  final bool active;
  final bool completedJustNow;
  final String title;
  final String stage;
  final String detail;
  final int percent;
  final int elapsedSeconds;
  final List<String> subagents;
}

class ReviewSession {
  const ReviewSession({
    required this.sessionId,
    required this.pr,
    required this.effortLevel,
    required this.commentsOnly,
    required this.analysisStatus,
    required this.cliffsNotes,
    required this.chapters,
    required this.threads,
    required this.coverageMatrix,
    required this.dismissedChecks,
    required this.topLevelComment,
    required this.repoDir,
    required this.workspaceDir,
    required this.conversationId,
    required this.isTutorial,
    this.securityGate,
    this.staleHeadInfo,
  });

  factory ReviewSession.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> rawPr =
        (json['pr'] as Map<String, dynamic>?) ?? const <String, dynamic>{};
    final Map<String, dynamic> rawCn =
        (json['cliffsNotes'] as Map<String, dynamic>?) ??
            const <String, dynamic>{};
    final Map<String, dynamic>? rawSg =
        json['securityGate'] is Map<String, dynamic>
            ? json['securityGate'] as Map<String, dynamic>
            : null;
    final Map<String, dynamic>? rawStale =
        json['staleHeadInfo'] is Map<String, dynamic>
            ? json['staleHeadInfo'] as Map<String, dynamic>
            : null;
    final List<dynamic> rawChapters =
        (json['chapters'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawThreads =
        (json['threads'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawCov =
        (json['coverageMatrix'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawDismissed =
        (json['dismissedChecks'] as List<dynamic>?) ?? const <dynamic>[];

    final SecurityGate? parsedSg =
        rawSg != null ? SecurityGate.fromJson(rawSg) : null;
    final StaleHeadInfo? parsedStale =
        rawStale != null ? StaleHeadInfo.fromJson(rawStale) : null;

    return ReviewSession(
      sessionId: '${json['sessionId'] ?? ''}',
      pr: PrMetadata.fromJson(rawPr),
      effortLevel: '${json['effortLevel'] ?? 'high'}',
      commentsOnly: json['commentsOnly'] == true,
      analysisStatus: '${json['analysisStatus'] ?? 'ready'}',
      cliffsNotes: CliffsNotesData.fromJson(rawCn),
      chapters: rawChapters
          .whereType<Map<String, dynamic>>()
          .map(ReviewChapter.fromJson)
          .toList(),
      threads: rawThreads
          .whereType<Map<String, dynamic>>()
          .map(ReviewThread.fromJson)
          .toList(),
      coverageMatrix: rawCov
          .whereType<Map<String, dynamic>>()
          .map(CoverageRow.fromJson)
          .toList(),
      dismissedChecks: rawDismissed.map((dynamic e) => '$e').toList(),
      topLevelComment: '${json['topLevelComment'] ?? ''}',
      repoDir: '${json['repoDir'] ?? ''}',
      workspaceDir: '${json['workspaceDir'] ?? ''}',
      conversationId: '${json['conversationId'] ?? ''}',
      isTutorial: json['isTutorial'] == true || rawPr['isTutorial'] == true,
      securityGate: (parsedSg != null && parsedSg.hasAlerts) ? parsedSg : null,
      staleHeadInfo:
          (parsedStale != null && parsedStale.isStaleHead) ? parsedStale : null,
    );
  }

  final String sessionId;
  final PrMetadata pr;
  final String effortLevel;
  final bool commentsOnly;
  final String analysisStatus;
  final CliffsNotesData cliffsNotes;
  final List<ReviewChapter> chapters;
  final List<ReviewThread> threads;
  final List<CoverageRow> coverageMatrix;
  final List<String> dismissedChecks;
  final String topLevelComment;
  final String repoDir;
  final String workspaceDir;
  final String conversationId;
  final bool isTutorial;
  final SecurityGate? securityGate;
  final StaleHeadInfo? staleHeadInfo;

  List<ReviewThread> get activeThreads =>
      threads.where((ReviewThread t) => t.status != 'dismissed').toList();

  List<TourStop> get allStops => <TourStop>[
        for (final ReviewChapter ch in chapters) ...ch.stops,
      ];
}

class PrMetadata {
  const PrMetadata({
    this.provider = 'github',
    this.patchSet,
    required this.owner,
    required this.repo,
    required this.number,
    required this.title,
    required this.url,
    required this.author,
    required this.baseRefName,
    required this.headRefName,
    required this.additions,
    required this.deletions,
    required this.changedFilesCount,
    required this.isOwnedByUser,
  });

  factory PrMetadata.fromJson(Map<String, dynamic> json) {
    return PrMetadata(
      provider: '${json['provider'] ?? 'github'}',
      patchSet: (json['patchSet'] as num?)?.toInt(),
      owner: '${json['owner'] ?? ''}',
      repo: '${json['repo'] ?? ''}',
      number: (json['number'] as num?)?.toInt(),
      title: '${json['title'] ?? 'Code Review'}',
      url: '${json['url'] ?? ''}',
      author: '${json['author'] ?? 'local'}',
      baseRefName: '${json['baseRefName'] ?? 'main'}',
      headRefName: '${json['headRefName'] ?? json['headBranch'] ?? 'HEAD'}',
      additions: (json['additions'] as num?)?.toInt() ?? 0,
      deletions: (json['deletions'] as num?)?.toInt() ?? 0,
      changedFilesCount: (json['changedFilesCount'] as num?)?.toInt() ?? 0,
      isOwnedByUser: json['isOwnedByUser'] != false,
    );
  }

  final String provider;
  final int? patchSet;
  bool get isGerrit => provider == 'gerrit';
  String get remoteLabel => isGerrit ? 'Gerrit' : 'GitHub';
  final String owner;
  final String repo;
  final int? number;
  final String title;
  final String url;
  final String author;
  final String baseRefName;
  final String headRefName;
  final int additions;
  final int deletions;
  final int changedFilesCount;
  final bool isOwnedByUser;
}

class SecuritySignal {
  const SecuritySignal({
    required this.severity,
    required this.category,
    required this.location,
    required this.detail,
    this.path = '',
    this.line = 1,
    this.excerpt = '',
  });

  factory SecuritySignal.fromJson(Map<String, dynamic> json) {
    return SecuritySignal(
      severity: '${json['severity'] ?? 'warning'}'.trim().toLowerCase(),
      category: '${json['category'] ?? 'security'}'.trim(),
      location: '${json['location'] ?? json['path'] ?? 'PR'}'.trim(),
      detail: '${json['detail'] ?? ''}'.trim(),
      path: '${json['path'] ?? ''}'.trim(),
      line: (json['line'] as num?)?.toInt() ?? 1,
      excerpt: '${json['excerpt'] ?? ''}'.trim(),
    );
  }

  final String severity;
  final String category;
  final String location;
  final String detail;
  final String path;
  final int line;
  final String excerpt;

  bool get isBlocked => severity == 'blocked';
}

class SecurityGate {
  const SecurityGate({
    required this.status,
    required this.haltLlmReview,
    required this.overridden,
    required this.summary,
    required this.signals,
  });

  factory SecurityGate.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawSignals =
        (json['signals'] as List<dynamic>?) ?? const <dynamic>[];
    final List<SecuritySignal> sigs = rawSignals
        .whereType<Map<String, dynamic>>()
        .map(SecuritySignal.fromJson)
        .where((SecuritySignal s) => s.detail.isNotEmpty)
        .toList();
    return SecurityGate(
      status: '${json['status'] ?? 'none'}'.trim().toLowerCase(),
      haltLlmReview: json['haltLlmReview'] == true,
      overridden: json['overridden'] == true,
      summary: '${json['summary'] ?? ''}'.trim(),
      signals: sigs,
    );
  }

  final String status;
  final bool haltLlmReview;
  final bool overridden;
  final String summary;
  final List<SecuritySignal> signals;

  bool get isBlocked => status == 'blocked';
  bool get isHalted => isBlocked && !overridden;
  bool get hasAlerts =>
      (status == 'blocked' || status == 'warning') && signals.isNotEmpty;
}

class IntentVsActuality {
  const IntentVsActuality({
    required this.status,
    required this.statedIntent,
    required this.actualBehavior,
    required this.discrepancies,
  });

  factory IntentVsActuality.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawDisc =
        (json['discrepancies'] as List<dynamic>?) ?? const <dynamic>[];
    final List<String> disc = rawDisc
        .map((dynamic e) => '$e'.trim())
        .where((String s) => s.isNotEmpty)
        .toList();
    final String rawStatus = '${json['status'] ?? ''}'.trim().toLowerCase();
    return IntentVsActuality(
      status: rawStatus.isNotEmpty
          ? rawStatus
          : (disc.isNotEmpty ? 'diverges' : 'aligned'),
      statedIntent: '${json['statedIntent'] ?? ''}'.trim(),
      actualBehavior: '${json['actualBehavior'] ?? ''}'.trim(),
      discrepancies: disc,
    );
  }

  final String status;
  final String statedIntent;
  final String actualBehavior;
  final List<String> discrepancies;

  bool get diverges => status == 'diverges' || discrepancies.isNotEmpty;
  bool get hasContent =>
      statedIntent.isNotEmpty ||
      actualBehavior.isNotEmpty ||
      discrepancies.isNotEmpty;
}

class StaleHeadInfo {
  const StaleHeadInfo({
    required this.isStaleHead,
    required this.reviewedHeadSha,
    required this.latestHeadSha,
    required this.prUrl,
  });

  factory StaleHeadInfo.fromJson(Map<String, dynamic> json) {
    return StaleHeadInfo(
      isStaleHead: json['isStaleHead'] == true,
      reviewedHeadSha: '${json['reviewedHeadSha'] ?? ''}',
      latestHeadSha: '${json['latestHeadSha'] ?? ''}',
      prUrl: '${json['prUrl'] ?? ''}',
    );
  }

  final bool isStaleHead;
  final String reviewedHeadSha;
  final String latestHeadSha;
  final String prUrl;
}

class DeltaSummary {
  const DeltaSummary({
    required this.fromSha,
    required this.toSha,
    required this.rebased,
    required this.deltaFilesCount,
    required this.unchangedFilesCount,
    required this.resolvedFindingsCount,
    required this.newFindingsCount,
    required this.summary,
  });

  factory DeltaSummary.fromJson(Map<String, dynamic> json) {
    return DeltaSummary(
      fromSha: '${json['fromSha'] ?? ''}',
      toSha: '${json['toSha'] ?? ''}',
      rebased: json['rebased'] == true,
      deltaFilesCount: (json['deltaFilesCount'] as num?)?.toInt() ?? 0,
      unchangedFilesCount: (json['unchangedFilesCount'] as num?)?.toInt() ?? 0,
      resolvedFindingsCount:
          (json['resolvedFindingsCount'] as num?)?.toInt() ?? 0,
      newFindingsCount: (json['newFindingsCount'] as num?)?.toInt() ?? 0,
      summary: '${json['summary'] ?? ''}',
    );
  }

  final String fromSha;
  final String toSha;
  final bool rebased;
  final int deltaFilesCount;
  final int unchangedFilesCount;
  final int resolvedFindingsCount;
  final int newFindingsCount;
  final String summary;

  bool get hasContent => fromSha.isNotEmpty || summary.isNotEmpty;
}

class CliffsNotesData {
  const CliffsNotesData({
    required this.tldr,
    required this.whatAndWhy,
    required this.architectureDiagram,
    required this.keySymbols,
    required this.designTradeoffs,
    this.intentVsActuality,
    this.deltaSummary,
  });

  factory CliffsNotesData.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawSyms =
        (json['keySymbols'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawTradeoffs =
        (json['designTradeoffs'] as List<dynamic>?) ?? const <dynamic>[];
    final Map<String, dynamic>? rawIva =
        json['intentVsActuality'] as Map<String, dynamic>?;
    final Map<String, dynamic>? rawDs =
        json['deltaSummary'] as Map<String, dynamic>?;
    return CliffsNotesData(
      tldr: '${json['tldr'] ?? ''}',
      whatAndWhy: '${json['whatAndWhy'] ?? ''}',
      architectureDiagram: '${json['architectureDiagram'] ?? ''}',
      keySymbols: rawSyms
          .whereType<Map<String, dynamic>>()
          .map(KeySymbol.fromJson)
          .toList(),
      designTradeoffs: rawTradeoffs.map((dynamic e) => '$e').toList(),
      intentVsActuality:
          rawIva != null ? IntentVsActuality.fromJson(rawIva) : null,
      deltaSummary: rawDs != null ? DeltaSummary.fromJson(rawDs) : null,
    );
  }

  final String tldr;
  final String whatAndWhy;
  final String architectureDiagram;
  final List<KeySymbol> keySymbols;
  final List<String> designTradeoffs;
  final IntentVsActuality? intentVsActuality;
  final DeltaSummary? deltaSummary;
}

class KeySymbol {
  const KeySymbol({required this.name, required this.role});

  factory KeySymbol.fromJson(Map<String, dynamic> json) {
    return KeySymbol(
      name: '${json['name'] ?? ''}',
      role: '${json['role'] ?? ''}',
    );
  }

  final String name;
  final String role;
}

class ReviewChapter {
  const ReviewChapter({
    required this.id,
    required this.title,
    required this.summary,
    required this.cliffsNotesBullets,
    required this.stops,
  });

  factory ReviewChapter.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawBullets =
        (json['cliffsNotesBullets'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawStops =
        (json['stops'] as List<dynamic>?) ?? const <dynamic>[];
    return ReviewChapter(
      id: '${json['id'] ?? ''}',
      title: '${json['title'] ?? 'Chapter'}',
      summary: '${json['summary'] ?? ''}',
      cliffsNotesBullets: rawBullets.map((dynamic e) => '$e').toList(),
      stops: rawStops
          .whereType<Map<String, dynamic>>()
          .map(TourStop.fromJson)
          .toList(),
    );
  }

  final String id;
  final String title;
  final String summary;
  final List<String> cliffsNotesBullets;
  final List<TourStop> stops;
}

class TourStop {
  const TourStop({
    required this.id,
    required this.stopNumber,
    required this.title,
    required this.path,
    required this.startLine,
    required this.endLine,
    required this.cliffsNotes,
    required this.whyItChanged,
    required this.callersAndInvariants,
    required this.read,
  });

  factory TourStop.fromJson(Map<String, dynamic> json) {
    final int start = (json['startLine'] as num?)?.toInt() ?? 1;
    return TourStop(
      id: '${json['id'] ?? ''}',
      stopNumber: '${json['stopNumber'] ?? ''}',
      title: '${json['title'] ?? ''}',
      path: '${json['path'] ?? ''}',
      startLine: start,
      endLine: (json['endLine'] as num?)?.toInt() ?? start,
      cliffsNotes: '${json['cliffsNotes'] ?? json['description'] ?? ''}',
      whyItChanged: '${json['whyItChanged'] ?? ''}',
      callersAndInvariants: '${json['callersAndInvariants'] ?? ''}',
      read: json['read'] == true,
    );
  }

  final String id;
  final String stopNumber;
  final String title;
  final String path;
  final int startLine;
  final int endLine;
  final String cliffsNotes;
  final String whyItChanged;
  final String callersAndInvariants;
  final bool read;
}

class ReviewThread {
  const ReviewThread({
    required this.id,
    required this.kind,
    required this.severity,
    required this.status,
    required this.sourceAgent,
    required this.sourceAgents,
    required this.path,
    required this.targetFile,
    required this.isTopLevel,
    required this.startLine,
    required this.endLine,
    required this.title,
    required this.whyItMatters,
    required this.draftComment,
    required this.author,
    required this.triageStatus,
    required this.triageCategory,
    required this.triageBadge,
    required this.triageLabel,
    required this.triageSummary,
    required this.whatIsDone,
    required this.whatIsNotDone,
    required this.whatShouldBeDone,
    required this.recommendedForFix,
    required this.selectedForFix,
    required this.fixStatus,
    required this.fixedSummary,
    required this.uncertaintyQuestion,
    required this.solutionOptions,
    required this.selectedSolutionId,
    required this.selectedSolution,
    required this.messages,
  });

  factory ReviewThread.fromJson(Map<String, dynamic> json) {
    final int start = (json['startLine'] as num?)?.toInt() ?? 1;
    final List<dynamic> rawOpts =
        (json['solutionOptions'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawMsgs =
        (json['messages'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawSrcAgents =
        (json['sourceAgents'] as List<dynamic>?) ?? const <dynamic>[];
    final List<String> parsedSrcAgents = rawSrcAgents
        .map((dynamic e) => '$e'.trim())
        .where((String s) => s.isNotEmpty)
        .toList();
    final String singleSrc = '${json['sourceAgent'] ?? ''}'.trim();
    if (singleSrc.isNotEmpty && !parsedSrcAgents.contains(singleSrc)) {
      parsedSrcAgents.insert(0, singleSrc);
    }
    return ReviewThread(
      id: '${json['id'] ?? ''}',
      kind: '${json['kind'] ?? 'ai_candidate'}',
      severity: '${json['severity'] ?? 'DESIGN'}',
      status: '${json['status'] ?? 'candidate'}',
      sourceAgent: parsedSrcAgents.isNotEmpty ? parsedSrcAgents.first : '',
      sourceAgents: parsedSrcAgents,
      path: '${json['path'] ?? ''}',
      targetFile: '${json['targetFile'] ?? ''}',
      isTopLevel: json['isTopLevel'] == true,
      startLine: start,
      endLine: (json['endLine'] as num?)?.toInt() ?? start,
      title: '${json['title'] ?? 'Comment'}',
      whyItMatters: '${json['whyItMatters'] ?? ''}',
      draftComment: '${json['draftComment'] ?? json['body'] ?? ''}',
      author: '${json['author'] ?? ''}',
      triageStatus: '${json['triageStatus'] ?? ''}',
      triageCategory: '${json['triageCategory'] ?? ''}',
      triageBadge: '${json['triageBadge'] ?? ''}',
      triageLabel: '${json['triageLabel'] ?? ''}',
      triageSummary: '${json['triageSummary'] ?? ''}',
      whatIsDone: '${json['whatIsDone'] ?? ''}',
      whatIsNotDone: '${json['whatIsNotDone'] ?? ''}',
      whatShouldBeDone: '${json['whatShouldBeDone'] ?? ''}',
      recommendedForFix: json['recommendedForFix'] == true,
      selectedForFix: json['selectedForFix'] == true,
      fixStatus: '${json['fixStatus'] ?? ''}',
      fixedSummary: '${json['fixedSummary'] ?? ''}',
      uncertaintyQuestion:
          '${json['uncertaintyQuestion'] ?? json['calibrationQuestion'] ?? ''}',
      solutionOptions: rawOpts
          .whereType<Map<String, dynamic>>()
          .map(SolutionOption.fromJson)
          .toList(),
      selectedSolutionId: '${json['selectedSolutionId'] ?? ''}',
      selectedSolution: '${json['selectedSolution'] ?? ''}',
      messages: rawMsgs
          .whereType<Map<String, dynamic>>()
          .map(ThreadMessage.fromJson)
          .toList(),
    );
  }

  final String id;
  final String kind;
  final String severity;
  final String status;
  final String sourceAgent;
  final List<String> sourceAgents;
  final String path;
  final String targetFile;
  final bool isTopLevel;
  final int startLine;
  final int endLine;
  final String title;
  final String whyItMatters;
  final String draftComment;
  final String author;
  final String triageStatus;
  final String triageCategory;
  final String triageBadge;
  final String triageLabel;
  final String triageSummary;
  final String whatIsDone;
  final String whatIsNotDone;
  final String whatShouldBeDone;
  final bool recommendedForFix;
  final bool selectedForFix;
  final String fixStatus;
  final String fixedSummary;
  final String uncertaintyQuestion;
  final List<SolutionOption> solutionOptions;
  final String selectedSolutionId;
  final String selectedSolution;
  final List<ThreadMessage> messages;

  bool get isGithubExisting => kind == 'github_existing';
  bool get isStaged => status == 'staged';
  bool get isUncertain => status == 'uncertain';
  bool get isFixed => status == 'fixed';

  String get displayPath =>
      (targetFile.isNotEmpty && path == 'TOP_LEVEL_PR_COMMENTS.md')
          ? targetFile
          : path;

  String get shortFileName {
    final String p = displayPath;
    if (p.isEmpty) {
      return 'Top-Level';
    }
    final int slash = p.lastIndexOf('/');
    return slash >= 0 ? p.substring(slash + 1) : p;
  }

  String get cleanTitle {
    return title.replaceFirst(
      RegExp(r'^(?:🛠️|⚠️|✅|💬|❓|👀|🤔|🔴|🟡|🟢)\s*\[[^\]]+\]\s*'),
      '',
    );
  }

  String get effectiveWhatIsDone {
    if (whatIsDone.trim().isNotEmpty) {
      return whatIsDone.trim();
    }
    if (triageStatus == 'addressed_or_refuted') {
      return triageSummary.isNotEmpty
          ? triageSummary
          : 'Already addressed in current code or thread.';
    }
    return 'Checked against current HEAD snapshot.';
  }

  String get effectiveWhatIsNotDone {
    if (whatIsNotDone.trim().isNotEmpty) {
      return whatIsNotDone.trim();
    }
    if (triageStatus == 'addressed_or_refuted') {
      return 'None — comment has been addressed.';
    }
    return triageSummary.isNotEmpty
        ? triageSummary
        : 'Needs review or code update.';
  }

  String get effectiveWhatShouldBeDone {
    if (whatShouldBeDone.trim().isNotEmpty) {
      return whatShouldBeDone.trim();
    }
    if (triageStatus == 'addressed_or_refuted') {
      return 'No code changes needed.';
    }
    return 'Update the implementation or reply in the PR thread.';
  }
}

class SolutionOption {
  const SolutionOption({
    required this.id,
    required this.label,
    required this.description,
    required this.recommended,
  });

  factory SolutionOption.fromJson(Map<String, dynamic> json) {
    return SolutionOption(
      id: '${json['id'] ?? ''}',
      label: '${json['label'] ?? ''}',
      description: '${json['description'] ?? ''}',
      recommended: json['recommended'] == true,
    );
  }

  final String id;
  final String label;
  final String description;
  final bool recommended;
}

class ThreadMessage {
  const ThreadMessage({
    required this.author,
    required this.body,
    required this.timestamp,
    required this.isTriageNote,
    required this.pending,
  });

  factory ThreadMessage.fromJson(Map<String, dynamic> json) {
    return ThreadMessage(
      author: '${json['author'] ?? 'Quasar'}',
      body: '${json['body'] ?? ''}',
      timestamp: '${json['timestamp'] ?? ''}',
      isTriageNote: json['isTriageNote'] == true,
      pending: json['pending'] == true,
    );
  }

  final String author;
  final String body;
  final String timestamp;
  final bool isTriageNote;
  final bool pending;
}

class CoverageRow {
  const CoverageRow({
    required this.behavior,
    required this.status,
    required this.notes,
  });

  factory CoverageRow.fromJson(Map<String, dynamic> json) {
    return CoverageRow(
      behavior: '${json['behavior'] ?? ''}',
      status: '${json['status'] ?? ''}',
      notes: '${json['notes'] ?? ''}',
    );
  }

  final String behavior;
  final String status;
  final String notes;
}

class FileDiff {
  const FileDiff({
    required this.path,
    required this.additions,
    required this.deletions,
    required this.rows,
  });

  factory FileDiff.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawRows =
        (json['rows'] as List<dynamic>?) ?? const <dynamic>[];
    return FileDiff(
      path: '${json['path'] ?? ''}',
      additions: (json['additions'] as num?)?.toInt() ?? 0,
      deletions: (json['deletions'] as num?)?.toInt() ?? 0,
      rows:
          rawRows.whereType<Map<String, dynamic>>().map(DiffRow.fromJson).toList(),
    );
  }

  final String path;
  final int additions;
  final int deletions;
  final List<DiffRow> rows;

  String get shortName {
    final int slash = path.lastIndexOf('/');
    return slash >= 0 ? path.substring(slash + 1) : path;
  }
}

class DiffRow {
  const DiffRow({
    required this.type,
    required this.baseLine,
    required this.headLine,
    required this.baseText,
    required this.headText,
  });

  factory DiffRow.fromJson(Map<String, dynamic> json) {
    return DiffRow(
      type: '${json['type'] ?? 'context'}'.trim(),
      baseLine: (json['baseLine'] as num?)?.toInt(),
      headLine: (json['headLine'] as num?)?.toInt(),
      baseText: '${json['baseText'] ?? ''}',
      headText: '${json['headText'] ?? ''}',
    );
  }

  final String type;
  final int? baseLine;
  final int? headLine;
  final String baseText;
  final String headText;
}

class FlowchartNode {
  const FlowchartNode({
    required this.id,
    required this.label,
    this.group,
  });

  final String id;
  final String label;
  final String? group;
}

class FlowchartEdge {
  const FlowchartEdge({
    required this.from,
    required this.to,
    this.label = '',
    this.dashed = false,
  });

  final String from;
  final String to;
  final String label;
  final bool dashed;
}

class FlowchartGraph {
  const FlowchartGraph({
    required this.nodes,
    required this.edges,
    required this.isTopDown,
  });

  final List<FlowchartNode> nodes;
  final List<FlowchartEdge> edges;
  final bool isTopDown;
}

FlowchartGraph parseMermaidFlowchart(String raw) {
  final Map<String, FlowchartNode> nodeMap = <String, FlowchartNode>{};
  final List<FlowchartEdge> edges = <FlowchartEdge>[];
  bool isTopDown = false;
  String? currentGroup;

  void ensureNode(String rawToken) {
    final String token = rawToken.trim();
    if (token.isEmpty) {
      return;
    }
    final RegExpMatch? m = RegExp(
      r'^([A-Za-z0-9_.-]+)\s*(?:\[\s*"?([^"\]]+)"?\s*\]|\(\s*"?([^"\)]+)"?\s*\)|\{\s*"?([^"\}]+)"?\s*\})?$',
    ).firstMatch(token);
    if (m == null) {
      return;
    }
    final String id = m.group(1)!;
    final String? parsedLabel = m.group(2) ?? m.group(3) ?? m.group(4);
    final FlowchartNode? existing = nodeMap[id];
    if (existing == null || (parsedLabel != null && existing.label == id)) {
      nodeMap[id] = FlowchartNode(
        id: id,
        label: (parsedLabel ?? existing?.label ?? id).trim(),
        group: currentGroup ?? existing?.group,
      );
    }
  }

  String extractId(String rawToken) {
    final RegExpMatch? m =
        RegExp(r'^([A-Za-z0-9_.-]+)').firstMatch(rawToken.trim());
    return m?.group(1) ?? rawToken.trim();
  }

  for (final String rawLine in raw.split('\n')) {
    final String line = rawLine.trim();
    if (line.isEmpty || line.startsWith('%%') || line.startsWith('```')) {
      continue;
    }
    if (line.startsWith('flowchart ') || line.startsWith('graph ')) {
      if (line.contains('TD') || line.contains('TB')) {
        isTopDown = true;
      }
      continue;
    }
    if (line.startsWith('subgraph ')) {
      final RegExpMatch? sm = RegExp(
        r'^subgraph\s+(?:[A-Za-z0-9_.-]+\s*\[\s*"?([^"\]]+)"?\s*\]|"?([^"]+)"?)$',
      ).firstMatch(line);
      currentGroup = (sm?.group(1) ?? sm?.group(2) ?? '')
          .replaceFirst('subgraph ', '')
          .trim();
      continue;
    }
    if (line == 'end') {
      currentGroup = null;
      continue;
    }
    if (line.startsWith('classDef ') ||
        line.startsWith('class ') ||
        line.startsWith('style ')) {
      continue;
    }

    final RegExp edgeRe = RegExp(
      r'^(.+?)\s*(-\.->|-->|==>|---)\s*(?:\|([^|]*)\|\s*)?(.+)$',
    );
    final RegExpMatch? em = edgeRe.firstMatch(line);
    if (em != null) {
      final String left = em.group(1)!.trim();
      final String arrow = em.group(2)!;
      final String edgeLabel = (em.group(3) ?? '').trim();
      final String right = em.group(4)!.trim();
      ensureNode(left);
      ensureNode(right);
      final String fromId = extractId(left);
      final String toId = extractId(right);
      if (fromId.isNotEmpty && toId.isNotEmpty) {
        edges.add(
          FlowchartEdge(
            from: fromId,
            to: toId,
            label: edgeLabel,
            dashed: arrow.contains('.'),
          ),
        );
      }
    } else {
      ensureNode(line);
    }
  }

  return FlowchartGraph(
    nodes: nodeMap.values.toList(),
    edges: edges,
    isTopDown: isTopDown,
  );
}
