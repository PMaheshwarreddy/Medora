import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/api_client.dart' show ApiException;
import '../../hospital/hospital_widgets.dart';
import '../../theme/medora_theme.dart';
import '../../widgets/medora_scaffold.dart' show MedoraCard, MedoraNotice;
import '../doctor_screen.dart' show DoctorApi;
import '../doctor_widgets.dart';

/// Patients waiting for a doctor: emergencies first, then by how long they
/// have waited; the doctor's own department, or every patient.
class QueuePage extends StatefulWidget {
  const QueuePage({super.key, required this.api, required this.onOpen});

  final DoctorApi api;
  final ValueChanged<String> onOpen;

  /// How often the queue refreshes by itself.
  static const refresh = Duration(seconds: 15);

  @override
  State<QueuePage> createState() => _QueuePageState();
}

class _QueuePageState extends State<QueuePage> {
  final _number = TextEditingController();
  bool _all = false;
  Map<String, dynamic>? _queue;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(QueuePage.refresh, (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _number.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final queue =
          await widget.api.get(
                '/queue',
                query: {'scope': _all ? 'all' : 'department'},
              )
              as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _queue = queue;
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  List<Map<String, dynamic>> get _patients =>
      ((_queue?['patients'] as List?) ?? const []).cast<Map<String, dynamic>>();

  /// Takes the patient (or continues one already with this doctor).
  Future<void> _take(Map<String, dynamic> p) async {
    if (p['mine'] != true) {
      try {
        await widget.api.send('POST', '/visits/${p['id']}/pick');
      } on ApiException catch (e) {
        setState(() => _error = e.message);
        await _load();
        return;
      }
    }
    widget.onOpen(p['id'] as String);
  }

  void _byNumber() {
    final wanted = _number.text.trim().toUpperCase();
    final match = _patients.where((p) => p['visitNumber'] == wanted);
    if (match.isEmpty) {
      setState(() => _error = 'No waiting patient has visit number $wanted.');
      return;
    }
    _take(match.first);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final department = _queue?['department'] as String? ?? '';
    final waiting = _patients.where((p) => p['status'] != 'in_consultation');
    final pressing = _patients.where(
      (p) => p['urgency'] == 'emergency' || p['urgency'] == 'urgent',
    );
    final mine = _patients.where((p) => p['mine'] == true);
    final longest = waiting.fold<int>(
      0,
      (most, p) => (p['waitingMinutes'] as int? ?? 0) > most
          ? p['waitingMinutes'] as int
          : most,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Tiles(
          minWidth: 210,
          children: [
            StatTile(
              label: 'Waiting',
              value: '${waiting.length}',
              icon: Icons.hourglass_top_rounded,
              note: waiting.isEmpty
                  ? 'No one waiting'
                  : 'Longest ${waited(longest)}',
            ),
            StatTile(
              label: 'Urgent or emergency',
              value: '${pressing.length}',
              icon: Icons.priority_high_rounded,
              color: pressing.isEmpty ? MedoraColors.teal : MedoraColors.danger,
              note: pressing.isEmpty ? 'Nothing pressing' : 'Shown first',
            ),
            StatTile(
              label: 'With you',
              value: '${mine.length}',
              icon: Icons.medical_services_outlined,
              color: MedoraColors.accent,
              note: 'In consultation',
            ),
            StatTile(
              label: 'Signed today',
              value: '${_queue?['doneToday'] ?? 0}',
              icon: Icons.verified_outlined,
              color: MedoraColors.teal,
              note: 'Final reports sent',
            ),
          ],
        ),
        const SizedBox(height: 24),
        MedoraCard(
          padding: const EdgeInsets.fromLTRB(20, 16, 14, 16),
          child: Wrap(
            spacing: 14,
            runSpacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            alignment: WrapAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('Patient queue', style: text.titleLarge),
                  Text(
                    department.isEmpty || _all
                        ? 'Every patient waiting at this hospital, most urgent first.'
                        : 'Patients for $department, most urgent first.',
                    style: text.bodyMedium?.copyWith(fontSize: 14),
                  ),
                ],
              ),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  if (department.isNotEmpty)
                    SegmentedButton<bool>(
                      showSelectedIcon: false,
                      segments: [
                        ButtonSegment(value: false, label: Text(department)),
                        const ButtonSegment(
                          value: true,
                          label: Text('All departments'),
                        ),
                      ],
                      selected: {_all},
                      onSelectionChanged: (v) {
                        setState(() => _all = v.first);
                        _load();
                      },
                    ),
                  SizedBox(
                    width: 220,
                    child: TextField(
                      key: const Key('visit-number'),
                      controller: _number,
                      textCapitalization: TextCapitalization.characters,
                      onSubmitted: (_) => _byNumber(),
                      decoration: const InputDecoration(
                        hintText: 'Visit number',
                        isDense: true,
                        prefixIcon: Icon(Icons.tag_rounded, size: 20),
                      ),
                    ),
                  ),
                  FilledButton.icon(
                    onPressed: _byNumber,
                    icon: const Icon(Icons.campaign_outlined, size: 18),
                    label: const Text('Call patient'),
                  ),
                  IconButton.outlined(
                    tooltip: 'Refresh',
                    onPressed: _load,
                    icon: const Icon(Icons.refresh_rounded),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (_error != null) ...[
          MedoraNotice(icon: Icons.error_outline, message: _error!),
          const SizedBox(height: 16),
        ],
        if (_queue == null)
          const Padding(
            padding: EdgeInsets.all(40),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (_patients.isEmpty)
          const _AllClear()
        else
          for (final p in _patients) ...[
            _PatientRow(patient: p, onTake: () => _take(p)),
            const SizedBox(height: 12),
          ],
      ],
    );
  }
}

/// Nobody is waiting.
class _AllClear extends StatelessWidget {
  const _AllClear();

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 24),
      child: Column(
        children: [
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: MedoraColors.teal.withValues(alpha: 0.1),
            ),
            child: const Icon(
              Icons.spa_outlined,
              size: 34,
              color: MedoraColors.teal,
            ),
          ),
          const SizedBox(height: 16),
          Text('No patients are waiting.', style: text.titleLarge),
          const SizedBox(height: 4),
          Text(
            'New visits from the kiosk appear here by themselves.',
            style: text.bodyMedium,
          ),
        ],
      ),
    );
  }
}

class _PatientRow extends StatelessWidget {
  const _PatientRow({required this.patient, required this.onTake});

  final Map<String, dynamic> patient;
  final VoidCallback onTake;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final p = patient;
    final color = urgencyColor(p['urgency']);
    final withOther = p['status'] == 'in_consultation' && p['mine'] != true;
    final minutes = p['waitingMinutes'] as int? ?? 0;
    final department = '${p['department'] ?? ''}';
    final wide = MediaQuery.sizeOf(context).width >= 760;
    final button = FilledButton.icon(
      key: Key('take-${p['id']}'),
      onPressed: withOther ? null : onTake,
      style: p['urgency'] == 'emergency'
          ? FilledButton.styleFrom(backgroundColor: MedoraColors.danger)
          : null,
      icon: Icon(
        p['mine'] == true
            ? Icons.play_arrow_rounded
            : Icons.arrow_forward_rounded,
        size: 18,
      ),
      label: Text(p['mine'] == true ? 'Continue' : 'See patient'),
    );
    final details = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text('${p['name']}', style: text.titleMedium),
            Text(
              ageAndSex(p['age'], p['gender']),
              style: text.bodyMedium?.copyWith(fontSize: 14),
            ),
            UrgencyTag(p['urgency'] as String?),
            if ((p['abnormalVitals'] as int? ?? 0) > 0)
              Tag(
                '${p['abnormalVitals']} vitals out of range',
                MedoraColors.accent,
              ),
            if (p['returning'] == true)
              const Tag('Returning', MedoraColors.navy),
            if (p['mine'] == true) const Tag('With you', MedoraColors.teal),
            if (withOther) Tag('With ${p['withDoctor']}', MedoraColors.muted),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          p['symptoms'] as String? ?? '',
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: text.bodyLarge?.copyWith(
            fontSize: 15,
            fontFamilyFallback: MedoraFonts.fallback,
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 16,
          runSpacing: 4,
          children: [
            _Meta(Icons.tag_rounded, p['visitNumber'] as String, mono: true),
            _Meta(Icons.schedule_rounded, 'Waiting ${waited(minutes)}'),
            if (department.isNotEmpty)
              _Meta(Icons.account_tree_outlined, 'Medora: $department'),
          ],
        ),
      ],
    );
    return MedoraCard(
      padding: EdgeInsets.zero,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              width: 5,
              decoration: BoxDecoration(
                color: color,
                borderRadius: const BorderRadius.horizontal(
                  left: Radius.circular(22),
                ),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                child: wide
                    ? Row(
                        children: [
                          Initials(p['name'], size: 50, color: color),
                          const SizedBox(width: 16),
                          Expanded(child: details),
                          const SizedBox(width: 16),
                          button,
                        ],
                      )
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          details,
                          const SizedBox(height: 12),
                          Align(
                            alignment: Alignment.centerRight,
                            child: button,
                          ),
                        ],
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A small icon with a few words, under a patient's name.
class _Meta extends StatelessWidget {
  const _Meta(this.icon, this.label, {this.mono = false});

  final IconData icon;
  final String label;
  final bool mono;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(icon, size: 15, color: MedoraColors.muted),
      const SizedBox(width: 5),
      Text(
        label,
        style: TextStyle(
          fontSize: 13.5,
          color: MedoraColors.muted,
          letterSpacing: mono ? 0.8 : null,
          fontWeight: mono ? FontWeight.w700 : FontWeight.w500,
        ),
      ),
    ],
  );
}
