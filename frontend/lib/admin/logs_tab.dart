import 'package:flutter/material.dart';

import '../theme/medora_theme.dart';
import 'admin_widgets.dart';

/// The activity feed: what each client's kiosks did, and what went wrong.
class LogsTab extends StatefulWidget {
  const LogsTab({super.key, required this.admin});

  final AdminApi admin;

  @override
  State<LogsTab> createState() => _LogsTabState();
}

class _LogsTabState extends State<LogsTab> with Loader {
  List<dynamic> _clients = [];
  List<dynamic> _logs = [];
  String? _clientId;
  String _level = '';

  @override
  Future<void> load() async {
    final results = await Future.wait([
      widget.admin.get('/api/admin/tenants'),
      widget.admin.get(
        '/api/admin/logs',
        query: {
          'limit': '300',
          'tenant_id': ?_clientId,
          if (_level.isNotEmpty) 'level': _level,
        },
      ),
    ]);
    _clients = results[0] as List;
    _logs = results[1] as List;
  }

  @override
  Widget build(BuildContext context) {
    final names = {for (final c in _clients) c['id']: c['name'] as String};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        Section(
          title: 'Activity log',
          subtitle: 'Newest first. Showing the latest 300 entries.',
          actions: [
            SegmentedButton<String>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: '', label: Text('All')),
                ButtonSegment(value: 'warning', label: Text('Warnings')),
                ButtonSegment(value: 'error', label: Text('Errors')),
              ],
              selected: {_level},
              onSelectionChanged: (s) {
                _level = s.first;
                run(() async {});
              },
            ),
            ClientFilter(
              clients: _clients,
              value: _clientId,
              onChanged: (id) {
                _clientId = id;
                run(() async {});
              },
            ),
            IconButton(
              tooltip: 'Refresh',
              onPressed: busy ? null : () => run(() async {}),
              icon: const Icon(Icons.refresh),
            ),
          ],
          child: _logs.isEmpty
              ? const EmptyNote('Nothing logged for this filter.')
              : AdminTable(
                  columns: const [
                    'Time',
                    'Level',
                    'Client',
                    'Event',
                    'Details',
                  ],
                  rows: [
                    for (final l in _logs)
                      [
                        Text(formatDate(l['at'])),
                        switch (l['level']) {
                          'error' => const Pill('Error', MedoraColors.danger),
                          'warning' => const Pill(
                            'Warning',
                            MedoraColors.warning,
                          ),
                          _ => const Pill('Info', MedoraColors.muted),
                        },
                        Text(names[l['tenantId']] ?? 'System'),
                        Text(l['event'] as String),
                        Clipped(l['message'] as String, width: 460),
                      ],
                  ],
                ),
        ),
      ],
    );
  }
}
