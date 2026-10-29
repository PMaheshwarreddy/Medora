import 'package:flutter/material.dart';

import '../../theme/medora_theme.dart';
import '../hospital_api.dart';
import '../hospital_widgets.dart';

/// Two records: the audit log (who did what in this portal, including who
/// opened which patient's visit) and the kiosks' activity.
class ActivityPage extends StatefulWidget {
  const ActivityPage({super.key, required this.api});

  final HospitalApi api;

  @override
  State<ActivityPage> createState() => _ActivityPageState();
}

class _ActivityPageState extends State<ActivityPage>
    with HospitalLoader<ActivityPage> {
  bool _kiosks = false;
  List<Map<String, dynamic>> _rows = [];

  @override
  Future<void> load() async {
    final rows = await widget.api.get(_kiosks ? '/activity' : '/audit');
    if (mounted) {
      setState(() => _rows = (rows as List).cast<Map<String, dynamic>>());
    }
  }

  static String _action(String action) => switch (action) {
    'visit.viewed' => 'Opened a patient visit',
    'account.signed_in' => 'Signed in',
    'account.password_changed' => 'Changed their password',
    'settings.updated' => 'Changed hospital settings',
    'department.created' => 'Added a department',
    'department.updated' => 'Changed a department',
    'hospital_admin.created' => 'Created a hospital admin',
    'hospital_admin.password_reset' => 'Reset a hospital admin\'s password',
    _ when action.endsWith('.created') =>
      'Added ${roleName(action.split('.').first).toLowerCase()}',
    _ when action.endsWith('.updated') =>
      'Changed ${roleName(action.split('.').first).toLowerCase()}',
    _ when action.endsWith('.password_reset') =>
      'Reset the password of ${roleName(action.split('.').first).toLowerCase()}',
    _ => action,
  };

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeading(
          'Audit and activity',
          'Who did what in this portal, and what the hospital\'s kiosks did.',
        ),
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(
              value: false,
              label: Text('Audit log'),
              icon: Icon(Icons.shield_outlined),
            ),
            ButtonSegment(
              value: true,
              label: Text('Kiosk activity'),
              icon: Icon(Icons.devices_outlined),
            ),
          ],
          selected: {_kiosks},
          onSelectionChanged: (v) {
            setState(() => _kiosks = v.first);
            run(() async {});
          },
        ),
        const SizedBox(height: 12),
        ...status(),
        Panel(
          title: _kiosks ? 'Kiosk activity' : 'Audit log',
          child: _kiosks
              ? Rows(
                  columns: const ['When', 'Event', 'Details'],
                  rows: [
                    for (final r in _rows)
                      [
                        Text(when(r['at'])),
                        Tag(r['event'] as String, switch (r['level']) {
                          'error' => MedoraColors.danger,
                          'warning' => MedoraColors.warning,
                          _ => MedoraColors.primary,
                        }),
                        SizedBox(
                          width: 520,
                          child: Text(r['message'] as String? ?? ''),
                        ),
                      ],
                  ],
                )
              : Rows(
                  columns: const ['When', 'Who', 'What', 'Details'],
                  rows: [
                    for (final r in _rows)
                      [
                        Text(when(r['at'])),
                        Text('${r['user']} (${roleName(r['role'])})'),
                        Text(_action(r['action'] as String)),
                        SizedBox(
                          width: 380,
                          child: Text(r['detail'] as String? ?? ''),
                        ),
                      ],
                  ],
                ),
        ),
      ],
    );
  }
}
