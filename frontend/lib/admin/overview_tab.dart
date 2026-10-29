import 'package:flutter/material.dart';

import '../theme/medora_theme.dart';
import 'admin_widgets.dart';

/// The dashboard: headline figures, the week's sessions, system health and
/// the latest activity.
class OverviewTab extends StatefulWidget {
  const OverviewTab({super.key, required this.admin});

  final AdminApi admin;

  @override
  State<OverviewTab> createState() => _OverviewTabState();
}

class _OverviewTabState extends State<OverviewTab> with Loader {
  Map<String, dynamic>? _data;
  Map<String, dynamic>? _knowledge;

  @override
  Future<void> load() async {
    final results = await Future.wait([
      widget.admin.get('/api/admin/overview'),
      widget.admin.get('/api/admin/knowledge/summary'),
    ]);
    _data = results[0] as Map<String, dynamic>;
    _knowledge = results[1] as Map<String, dynamic>;
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final k = _knowledge;
    if (d == null) return Column(children: statusWidgets());
    final errors = d['errorsLast24h'] as int;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        _Hero(
          name: widget.admin.user['name'] as String? ?? '',
          today: d['sessionsLast24h'] as int,
          online: d['online'] as bool,
        ),
        const SizedBox(height: 16),
        TileGrid(
          minTileWidth: 200,
          children: [
            KpiCard(
              icon: Icons.apartment_outlined,
              color: MedoraColors.primary,
              label: 'Clients',
              value: '${d['activeClients']}',
              detail: '${d['clients']} in total',
            ),
            KpiCard(
              icon: Icons.people_alt_outlined,
              color: MedoraColors.teal,
              label: 'Patient sessions',
              value: formatCount(d['sessions'] as int),
              detail: '${d['sessionsLast24h']} in 24 hours',
            ),
            KpiCard(
              icon: Icons.description_outlined,
              color: MedoraColors.violet,
              label: 'Reports generated',
              value: formatCount(d['reports'] as int),
            ),
            KpiCard(
              icon: Icons.key_outlined,
              color: MedoraColors.ochre,
              label: 'API calls, 24 hours',
              value: formatCount(d['apiCallsLast24h'] as int),
              detail: '${d['apiKeys']} active keys',
            ),
            KpiCard(
              icon: errors == 0
                  ? Icons.check_circle_outline
                  : Icons.error_outline,
              color: errors == 0 ? MedoraColors.teal : MedoraColors.danger,
              label: 'Errors, 24 hours',
              value: '$errors',
              detail: errors == 0 ? 'Nothing to look at' : 'See Activity logs',
            ),
          ],
        ),
        const SizedBox(height: 16),
        SplitRow(
          left: Section(
            title: 'Patient sessions, last 7 days',
            child: _WeekChart(days: (d['sessionsByDay'] as List).cast()),
          ),
          right: Section(title: 'System health', child: _Health(d, k)),
        ),
        const SizedBox(height: 16),
        SplitRow(
          leftFlex: 2,
          rightFlex: 3,
          left: Section(
            title: 'Sessions by client',
            child: _ClientBars(rows: (d['sessionsByClient'] as List).cast()),
          ),
          right: Section(
            title: 'Recent activity',
            child: _Activity(rows: (d['recentActivity'] as List).cast()),
          ),
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: busy ? null : () => run(() async {}),
            icon: const Icon(Icons.refresh),
            label: const Text('Refresh'),
          ),
        ),
      ],
    );
  }
}

/// One bar per day. A single series in a single colour: the title names it,
/// so there is no legend; exact values are on hover and on the latest bar.
class _WeekChart extends StatelessWidget {
  const _WeekChart({required this.days});

  final List<Map<String, dynamic>> days;

  static const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final counts = [for (final d in days) d['count'] as int];
    final peak = counts.fold(0, (a, b) => a > b ? a : b);
    if (peak == 0) {
      return const SizedBox(
        height: 212,
        child: EmptyNote('No patient sessions in the last 7 days.'),
      );
    }
    const plotHeight = 150.0;
    return SizedBox(
      height: 212,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final (i, day) in days.indexed)
            Expanded(
              child: Tooltip(
                message:
                    '${day['date']}: ${counts[i]} '
                    '${counts[i] == 1 ? 'session' : 'sessions'}',
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    // Label only the peak and today, not every bar.
                    Text(
                      counts[i] == peak || i == days.length - 1
                          ? '${counts[i]}'
                          : '',
                      style: text.bodyMedium?.copyWith(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: MedoraColors.text,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Container(
                      width: 34,
                      // A day with sessions always shows at least a sliver.
                      height: counts[i] == 0
                          ? 0
                          : (plotHeight * counts[i] / peak).clamp(
                              3,
                              plotHeight,
                            ),
                      decoration: const BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [
                            MedoraColors.primary,
                            MedoraColors.primaryDark,
                          ],
                        ),
                        borderRadius: BorderRadius.vertical(
                          top: Radius.circular(8),
                        ),
                      ),
                    ),
                    Container(height: 1, color: MedoraColors.border),
                    const SizedBox(height: 6),
                    Text(
                      _weekdays[DateTime.parse(day['date'] as String).weekday -
                          1],
                      style: text.bodyMedium?.copyWith(fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _ClientBars extends StatelessWidget {
  const _ClientBars({required this.rows});

  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const EmptyNote('No sessions yet.');
    final text = Theme.of(context).textTheme;
    final peak = rows.first['count'] as int;
    return Column(
      children: [
        for (final row in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        row['name'] as String,
                        style: text.titleMedium?.copyWith(fontSize: 15),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Text(
                      formatCount(row['count'] as int),
                      style: text.titleMedium?.copyWith(fontSize: 15),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: (row['count'] as int) / peak,
                    minHeight: 8,
                    backgroundColor: AdminColors.canvas,
                    color: MedoraColors.primary,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// Each line pairs an icon and a word with the colour, so state is never
/// carried by colour alone.
class _Health extends StatelessWidget {
  const _Health(this.overview, this.knowledge);

  final Map<String, dynamic> overview;
  final Map<String, dynamic>? knowledge;

  @override
  Widget build(BuildContext context) {
    final online = overview['online'] as bool;
    final voice = overview['voice'] as Map;
    final sync = overview['sync'] as Map;
    final k = knowledge;

    final (bool mirrorOk, String mirror) = !(sync['configured'] as bool)
        ? (false, 'Not set up')
        : (sync['lastError'] as String).isNotEmpty
        ? (false, 'Failing: ${sync['lastError']}')
        : (sync['pending'] as int) > 0
        ? (true, '${formatCount(sync['pending'] as int)} rows waiting to copy')
        : (true, 'Up to date, last copied ${formatDate(sync['lastSuccess'])}');

    return Column(
      children: [
        _HealthLine(
          'Connection',
          online,
          online ? 'Online' : 'Offline: working from the local database',
          warnOnly: true,
        ),
        _HealthLine(
          'Voice agent',
          voice['available'] as bool,
          voice['detail'] as String,
          warnOnly: true,
        ),
        _HealthLine('Report model', true, overview['reportModel'] as String),
        _HealthLine('Central database copy', mirrorOk, mirror),
        _HealthLine(
          'Medical knowledge',
          k != null && k['ready'] == true,
          k != null && k['ready'] == true
              ? '${formatCount(k['diseases'] as int)} diseases, '
                    '${formatCount(k['symptoms'] as int)} symptoms, '
                    '${formatCount(k['drugs'] as int)} drugs'
              : 'Not loaded',
        ),
      ],
    );
  }
}

class _HealthLine extends StatelessWidget {
  const _HealthLine(this.label, this.ok, this.detail, {this.warnOnly = false});

  final String label;
  final bool ok;
  final String detail;

  /// Not being ok is a limitation, not a fault (for example being offline).
  final bool warnOnly;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final color = ok
        ? MedoraColors.teal
        : warnOnly
        ? MedoraColors.warning
        : MedoraColors.danger;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(ok ? Icons.check_circle : Icons.error, color: color, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: text.titleMedium?.copyWith(fontSize: 15)),
                Text(
                  detail,
                  style: text.bodyMedium?.copyWith(fontSize: 13),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Activity extends StatelessWidget {
  const _Activity({required this.rows});

  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const EmptyNote('Nothing has happened yet.');
    final text = Theme.of(context).textTheme;
    return Column(
      children: [
        for (final row in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: switch (row['level']) {
                    'error' => const Icon(
                      Icons.error,
                      size: 18,
                      color: MedoraColors.danger,
                    ),
                    'warning' => const Icon(
                      Icons.warning_amber,
                      size: 18,
                      color: MedoraColors.warning,
                    ),
                    _ => const Icon(
                      Icons.circle,
                      size: 10,
                      color: MedoraColors.border,
                    ),
                  },
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        row['message'] as String,
                        style: const TextStyle(
                          fontSize: 14.5,
                          color: MedoraColors.text,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        '${row['client']}  ·  ${formatDate(row['at'])}',
                        style: text.bodyMedium?.copyWith(fontSize: 12.5),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// The greeting across the top of the dashboard.
class _Hero extends StatelessWidget {
  const _Hero({required this.name, required this.today, required this.online});

  final String name;
  final int today;
  final bool online;

  @override
  Widget build(BuildContext context) {
    final hour = DateTime.now().hour;
    final greeting = hour < 12
        ? 'Good morning'
        : hour < 17
        ? 'Good afternoon'
        : 'Good evening';
    final first = name.trim().split(' ').first;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 28),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        gradient: MedoraTheme.brandGradient,
        borderRadius: BorderRadius.circular(24),
        boxShadow: const [
          BoxShadow(
            color: Color(0x261D4D3B),
            blurRadius: 30,
            offset: Offset(0, 14),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  first.isEmpty ? greeting : '$greeting, $first',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 30,
                    fontFamily: MedoraFonts.serif,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -0.6,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  today == 0
                      ? 'No patients have checked in during the last 24 hours.'
                      : today == 1
                      ? '1 patient checked in during the last 24 hours.'
                      : '$today patients checked in during the last 24 hours.',
                  style: const TextStyle(
                    color: Color(0xFFDCE7E0),
                    fontSize: 16,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 16),
          Container(
            width: 76,
            height: 76,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: Color(0x26FFFFFF),
            ),
            child: Icon(
              online ? Icons.monitor_heart_outlined : Icons.cloud_off_outlined,
              color: Colors.white,
              size: 38,
            ),
          ),
        ],
      ),
    );
  }
}
