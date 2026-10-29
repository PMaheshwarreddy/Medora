import 'package:flutter/material.dart';

import '../theme/medora_theme.dart';
import 'admin_widgets.dart';

/// Patient intakes across all clients, newest first.
class SessionsTab extends StatefulWidget {
  const SessionsTab({super.key, required this.admin});

  final AdminApi admin;

  @override
  State<SessionsTab> createState() => _SessionsTabState();
}

class _SessionsTabState extends State<SessionsTab> with Loader {
  List<dynamic> _clients = [];
  List<dynamic> _sessions = [];
  String? _clientId;

  @override
  Future<void> load() async {
    final results = await Future.wait([
      widget.admin.get('/api/admin/tenants'),
      widget.admin.get(
        '/api/sessions',
        query: {'limit': '200', 'tenant_id': ?_clientId},
      ),
    ]);
    _clients = results[0] as List;
    _sessions = results[1] as List;
  }

  @override
  Widget build(BuildContext context) {
    final names = {for (final c in _clients) c['id']: c['name'] as String};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        Section(
          title: 'Patient sessions',
          subtitle: 'Intakes confirmed on a kiosk. Showing the latest 200.',
          actions: [
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
          child: _sessions.isEmpty
              ? const EmptyNote('No patient sessions yet.')
              : AdminTable(
                  columns: const [
                    'Time',
                    'Client',
                    'Patient',
                    'Age',
                    'Gender',
                    'Phone',
                    'Intake',
                    'Vitals',
                    'Report',
                    'Symptoms',
                  ],
                  rows: [
                    for (final s in _sessions)
                      [
                        Text(formatDate(s['createdAt'])),
                        Text(names[s['tenantId']] ?? '–'),
                        Text(s['name'] as String),
                        Text('${s['age']}'),
                        Text(s['gender'] as String),
                        Text(s['phone'] as String),
                        Text(s['mode'] as String),
                        Text(s['vitals'] != null ? 'Yes' : 'No'),
                        s['hasReport'] == true
                            ? const Pill('Generated', MedoraColors.teal)
                            : const Pill('None', MedoraColors.muted),
                        Clipped(s['symptoms'] as String),
                      ],
                  ],
                ),
        ),
      ],
    );
  }
}
