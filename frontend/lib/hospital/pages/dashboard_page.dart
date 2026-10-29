import 'package:flutter/material.dart';

import '../../theme/medora_theme.dart';
import '../hospital_api.dart';
import '../hospital_screen.dart' show HospitalPage;
import '../hospital_widgets.dart';

/// Today at this hospital: visits, reports, urgent cases, departments,
/// the week, and the latest visits.
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key, required this.api, required this.onOpen});

  final HospitalApi api;
  final ValueChanged<HospitalPage> onOpen;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage>
    with HospitalLoader<DashboardPage> {
  Map<String, dynamic>? _data;

  @override
  Future<void> load() async {
    final data = await widget.api.get('/dashboard') as Map<String, dynamic>;
    if (mounted) setState(() => _data = data);
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final hour = DateTime.now().hour;
    final greeting = hour < 12
        ? 'Good morning'
        : hour < 17
        ? 'Good afternoon'
        : 'Good evening';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PageHeading(
          '$greeting, ${(widget.api.user['name'] as String? ?? '').split(' ').first}',
          'Today at ${widget.api.hospital['name']}.',
          action: OutlinedButton.icon(
            onPressed: () => run(() async {}),
            icon: const Icon(Icons.refresh_rounded),
            label: const Text('Refresh'),
          ),
        ),
        ...status(),
        if (d != null) ..._body(context, d),
      ],
    );
  }

  List<Widget> _body(BuildContext context, Map<String, dynamic> d) {
    final today = d['today'] as Map<String, dynamic>;
    final people = d['people'] as Map<String, dynamic>;
    final byUrgency = (today['byUrgency'] as Map).cast<String, dynamic>();
    final departments = (today['byDepartment'] as List).cast<Map>();
    final week = (d['week'] as List).cast<Map>();
    final recent = (d['recent'] as List).cast<Map>();
    final weekMax = week.fold<int>(
      1,
      (m, w) => (w['visits'] as int) > m ? w['visits'] as int : m,
    );
    return [
      Tiles(
        children: [
          Figure(
            'Visits today',
            '${today['visits']}',
            icon: Icons.people_alt_outlined,
          ),
          Figure(
            'Reports today',
            '${today['reports']}',
            icon: Icons.description_outlined,
            color: MedoraColors.teal,
          ),
          Figure(
            'Urgent or emergency',
            '${today['urgent']}',
            icon: Icons.priority_high_rounded,
            color: (today['urgent'] as int) > 0
                ? MedoraColors.accent
                : MedoraColors.muted,
          ),
          Figure(
            'Doctors',
            '${people['doctors']}',
            icon: Icons.medical_services_outlined,
            color: MedoraColors.navy,
          ),
        ],
      ),
      const SizedBox(height: 20),
      Tiles(
        minWidth: 360,
        children: [
          Panel(
            title: 'Today by urgency',
            child: Column(
              children: [
                for (final (key, label, color) in const [
                  ('emergency', 'Emergency', MedoraColors.danger),
                  ('urgent', 'Urgent', MedoraColors.warning),
                  ('soon', 'Soon', MedoraColors.primary),
                  ('routine', 'Routine', MedoraColors.teal),
                ])
                  _Bar(
                    label,
                    byUrgency[key] as int,
                    today['reports'] as int,
                    color,
                  ),
              ],
            ),
          ),
          Panel(
            title: 'Today by department',
            subtitle: 'Where the reports sent patients.',
            child: departments.isEmpty
                ? const Rows(columns: [], rows: [])
                : Column(
                    children: [
                      for (final row in departments.take(6))
                        _Bar(
                          row['department'] as String,
                          row['visits'] as int,
                          today['reports'] as int,
                          MedoraColors.primary,
                        ),
                    ],
                  ),
          ),
        ],
      ),
      const SizedBox(height: 20),
      Panel(
        title: 'The last 7 days',
        child: SizedBox(
          height: 150,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              for (final w in week)
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 6),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Text(
                          '${w['visits']}',
                          style: const TextStyle(fontSize: 13),
                        ),
                        const SizedBox(height: 4),
                        Container(
                          height: 100 * (w['visits'] as int) / weekMax + 2,
                          decoration: BoxDecoration(
                            color: MedoraColors.primary,
                            borderRadius: const BorderRadius.vertical(
                              top: Radius.circular(4),
                            ),
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          _weekday(w['date'] as String),
                          style: const TextStyle(
                            fontSize: 12.5,
                            color: MedoraColors.muted,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 20),
      Panel(
        title: 'Latest visits',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Rows(
              columns: const ['When', 'Patient', 'Urgency', 'Department'],
              rows: [
                for (final v in recent)
                  [
                    Text(when(v['at'])),
                    Text('${v['name']}, ${v['age']}'),
                    UrgencyTag(v['urgency'] as String?),
                    Text(v['department'] as String? ?? '—'),
                  ],
              ],
            ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => widget.onOpen(HospitalPage.visits),
                child: const Text('All visits'),
              ),
            ),
          ],
        ),
      ),
    ];
  }

  String _weekday(String iso) {
    const names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    final t = DateTime.tryParse(iso)?.toLocal();
    return t == null ? '' : names[t.weekday - 1];
  }
}

class _Bar extends StatelessWidget {
  const _Bar(this.label, this.value, this.total, this.color);

  final String label;
  final int value;
  final int total;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final share = total == 0 ? 0.0 : value / total;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(
            width: 150,
            child: Text(label, overflow: TextOverflow.ellipsis),
          ),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: LinearProgressIndicator(
                value: share,
                minHeight: 10,
                color: color,
                backgroundColor: MedoraColors.border,
              ),
            ),
          ),
          SizedBox(
            width: 40,
            child: Text(
              '$value',
              textAlign: TextAlign.right,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}
