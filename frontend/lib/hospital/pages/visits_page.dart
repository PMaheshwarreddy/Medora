import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api/api_client.dart' show ApiException;
import '../../theme/medora_theme.dart';
import '../hospital_api.dart';
import '../hospital_widgets.dart';

/// Every kiosk visit at this hospital and its report. Opening one is
/// written to the audit log (by the server).
class VisitsPage extends StatefulWidget {
  const VisitsPage({super.key, required this.api});

  final HospitalApi api;

  @override
  State<VisitsPage> createState() => _VisitsPageState();
}

class _VisitsPageState extends State<VisitsPage>
    with HospitalLoader<VisitsPage> {
  final _search = TextEditingController();
  List<Map<String, dynamic>> _visits = [];

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Future<void> load() async {
    final rows = await widget.api.get(
      '/visits',
      query: {
        if (_search.text.trim().isNotEmpty) 'search': _search.text.trim(),
      },
    );
    if (mounted) {
      setState(() => _visits = (rows as List).cast<Map<String, dynamic>>());
    }
  }

  Future<void> _open(Map<String, dynamic> visit) async {
    final Map<String, dynamic> detail;
    try {
      detail =
          await widget.api.get('/visits/${visit['id']}')
              as Map<String, dynamic>;
    } on ApiException catch (e) {
      setState(() => error = e.message);
      return;
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _VisitDialog(api: widget.api, visit: detail),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeading(
          'Visits and reports',
          'Every patient who used this hospital\'s kiosks. Opening a visit '
              'is recorded in the audit log.',
        ),
        ...status(),
        Panel(
          title: '${_visits.length} visits',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                key: const Key('visit-search'),
                controller: _search,
                onSubmitted: (_) => run(() async {}),
                decoration: InputDecoration(
                  labelText: 'Search by name or phone number',
                  prefixIcon: const Icon(Icons.search_rounded),
                  suffixIcon: IconButton(
                    tooltip: 'Search',
                    onPressed: () => run(() async {}),
                    icon: const Icon(Icons.arrow_forward_rounded),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Rows(
                columns: const [
                  'When',
                  'Patient',
                  'Phone',
                  'Symptoms',
                  'Urgency',
                  'Department',
                  'Doctor',
                ],
                onTap: (i) => _open(_visits[i]),
                rows: [
                  for (final v in _visits)
                    [
                      Text(when(v['at'])),
                      Text(
                        '${v['name']}, ${v['age']} ${(v['gender'] as String? ?? '').isEmpty ? '' : (v['gender'] as String)[0].toUpperCase()}',
                      ),
                      Text(v['phone'] as String? ?? ''),
                      SizedBox(
                        width: 260,
                        child: Text(
                          v['symptoms'] as String? ?? '',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      UrgencyTag(v['urgency'] as String?),
                      Text(v['department'] as String? ?? '—'),
                      switch (v['doctorStatus']) {
                        'signed' => Tag(
                          'Signed by ${v['doctor']}',
                          MedoraColors.teal,
                        ),
                        'with_doctor' => Tag(
                          'With ${v['doctor']}',
                          MedoraColors.primary,
                        ),
                        'waiting' => const Tag('Waiting', MedoraColors.ochre),
                        _ => const Text('—'),
                      },
                    ],
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _VisitDialog extends StatelessWidget {
  const _VisitDialog({required this.api, required this.visit});

  final HospitalApi api;
  final Map<String, dynamic> visit;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final report = visit['report'] as Map<String, dynamic>?;
    final vitals = (report?['vitalsAssessment'] as List? ?? const [])
        .cast<Map>();
    final conditions = (report?['possibleConditions'] as List? ?? const [])
        .cast<Map>();
    final medicines = (report?['medicines'] as List? ?? const []).cast<Map>();

    Widget row(String label, Object? value) {
      final shown = '${value ?? ''}'.trim();
      if (shown.isEmpty) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 150,
              child: Text(
                label,
                style: text.bodyMedium?.copyWith(fontSize: 14),
              ),
            ),
            Expanded(child: Text(shown)),
          ],
        ),
      );
    }

    return AlertDialog(
      title: Row(
        children: [
          Expanded(child: Text('${visit['name']}, ${visit['age']}')),
          UrgencyTag(visit['urgency'] as String?),
        ],
      ),
      content: SizedBox(
        width: 640,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(when(visit['at']), style: text.bodyMedium),
              const SizedBox(height: 14),
              row('Gender', visit['gender']),
              row('Phone', visit['phone']),
              row('Email', visit['email']),
              row('Symptoms', visit['symptoms']),
              row('Since', visit['duration']),
              row('Medicines taken', visit['medications']),
              row('Allergies', visit['allergies']),
              row(
                'Language',
                visit['language'] == 'ml' ? 'Malayalam' : 'English',
              ),
              if (report == null)
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text('No report was made for this visit.'),
                )
              else ...[
                const Divider(height: 28),
                Text('Report', style: text.titleLarge),
                const SizedBox(height: 10),
                row('Department', report['department']),
                row('Summary', report['clinicalSummary'] ?? report['summary']),
                if (vitals.isNotEmpty)
                  row(
                    'Vitals',
                    vitals
                        .map(
                          (v) => '${v['name']} ${v['value']} (${v['status']})',
                        )
                        .join(';  '),
                  ),
                if (conditions.isNotEmpty)
                  row(
                    'Possible conditions',
                    conditions
                        .map((c) => '${c['name']} (${c['likelihood']})')
                        .join(';  '),
                  ),
                if (medicines.isNotEmpty)
                  row(
                    'Medicines',
                    medicines
                        .map(
                          (m) =>
                              '${m['name']} ${m['strength'] ?? ''} ${m['dose'] ?? ''}, ${m['frequency'] ?? ''}',
                        )
                        .join(';  '),
                  ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        if (report != null)
          OutlinedButton.icon(
            onPressed: () => launchUrl(api.reportPdf(visit['id'] as String)),
            icon: const Icon(Icons.picture_as_pdf_outlined),
            label: const Text('Open PDF'),
          ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          style: FilledButton.styleFrom(backgroundColor: MedoraColors.primary),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
