import 'package:flutter/material.dart';

import '../../api/api_client.dart' show ApiException;
import '../../hospital/hospital_widgets.dart';
import '../../widgets/medora_scaffold.dart' show MedoraNotice;
import '../../theme/medora_theme.dart';
import '../doctor_screen.dart' show DoctorApi;
import '../doctor_widgets.dart';

/// The doctor's signed consultations, newest first.
class ConsultationsPage extends StatefulWidget {
  const ConsultationsPage({super.key, required this.api});

  final DoctorApi api;

  @override
  State<ConsultationsPage> createState() => _ConsultationsPageState();
}

class _ConsultationsPageState extends State<ConsultationsPage> {
  List<Map<String, dynamic>>? _rows;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows = await widget.api.get('/consultations') as List;
      if (mounted) setState(() => _rows = rows.cast<Map<String, dynamic>>());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows ?? const [];
    final today = DateTime.now();
    final signedToday = rows.where((r) {
      final at = DateTime.tryParse('${r['finalizedAt']}')?.toLocal();
      return at != null &&
          at.year == today.year &&
          at.month == today.month &&
          at.day == today.day;
    }).length;
    final medicines = rows.fold<int>(
      0,
      (sum, r) => sum + (r['medicines'] as int? ?? 0),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null) ...[
          MedoraNotice(icon: Icons.error_outline, message: _error!),
          const SizedBox(height: 16),
        ],
        if (_rows == null && _error == null)
          const Padding(
            padding: EdgeInsets.all(40),
            child: Center(child: CircularProgressIndicator()),
          ),
        if (_rows != null) ...[
          Tiles(
            minWidth: 210,
            children: [
              StatTile(
                label: 'Signed today',
                value: '$signedToday',
                icon: Icons.today_outlined,
                color: MedoraColors.teal,
              ),
              StatTile(
                label: 'Signed in all',
                value: '${rows.length}',
                icon: Icons.verified_outlined,
              ),
              StatTile(
                label: 'Medicines prescribed',
                value: '$medicines',
                icon: Icons.medication_outlined,
                color: MedoraColors.accent,
              ),
            ],
          ),
          const SizedBox(height: 20),
          Section(
            icon: Icons.task_alt_rounded,
            title: 'My consultations',
            subtitle: 'Patients you have signed reports for, newest first.',
            child: Rows(
              columns: const [
                'Signed',
                'Visit',
                'Patient',
                'Diagnosis',
                'Medicines',
              ],
              rows: [
                for (final r in rows)
                  [
                    Text(when(r['finalizedAt'])),
                    Text(
                      r['visitNumber'] as String,
                      style: const TextStyle(
                        letterSpacing: 0.8,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Initials(r['name'], size: 30),
                        const SizedBox(width: 10),
                        Text('${r['name']}, ${r['age']}'),
                      ],
                    ),
                    SizedBox(
                      width: 320,
                      child: Text((r['diagnosis'] as List).join(', ')),
                    ),
                    Text('${r['medicines']}'),
                  ],
              ],
            ),
          ),
        ],
      ],
    );
  }
}
