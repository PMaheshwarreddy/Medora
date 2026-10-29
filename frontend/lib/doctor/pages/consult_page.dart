import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api/api_client.dart' show ApiException;
import '../../hospital/hospital_widgets.dart';
import '../../theme/medora_theme.dart';
import '../../widgets/medora_scaffold.dart' show MedoraCard, MedoraNotice;
import '../doctor_screen.dart' show DoctorApi;
import '../doctor_widgets.dart';

/// One consultation. Left: Medora's doctor report (everything, including
/// what the patient's copy leaves out) and the patient's history. Right:
/// the doctor's own decisions, which become the patient's signed report.
class ConsultPage extends StatefulWidget {
  const ConsultPage({
    super.key,
    required this.api,
    required this.visitId,
    required this.onClose,
  });

  final DoctorApi api;
  final String visitId;
  final VoidCallback onClose;

  @override
  State<ConsultPage> createState() => _ConsultPageState();
}

/// One editable line of the prescription.
class _Med {
  _Med(Map<String, dynamic> m)
    : fromAi = m['fromAi'] == true,
      form = (m['form'] as String?) ?? '',
      name = TextEditingController(text: m['name'] as String? ?? ''),
      strength = TextEditingController(text: m['strength'] as String? ?? ''),
      dose = TextEditingController(text: m['dose'] as String? ?? ''),
      route = TextEditingController(text: m['route'] as String? ?? ''),
      frequency = TextEditingController(text: m['frequency'] as String? ?? ''),
      duration = TextEditingController(text: m['duration'] as String? ?? ''),
      maxDaily = TextEditingController(text: m['maxDaily'] as String? ?? ''),
      instructions = TextEditingController(
        text: m['instructions'] as String? ?? '',
      );

  final bool fromAi;
  String form;
  final TextEditingController name;
  final TextEditingController strength;
  final TextEditingController dose;
  final TextEditingController route;
  final TextEditingController frequency;
  final TextEditingController duration;
  final TextEditingController maxDaily;
  final TextEditingController instructions;

  List<TextEditingController> get _all => [
    name,
    strength,
    dose,
    route,
    frequency,
    duration,
    maxDaily,
    instructions,
  ]; // fmt: skip

  Map<String, dynamic> toJson() => {
    'name': name.text.trim(),
    'form': form,
    'strength': strength.text.trim(),
    'dose': dose.text.trim(),
    'route': route.text.trim(),
    'frequency': frequency.text.trim(),
    'duration': duration.text.trim(),
    'maxDaily': maxDaily.text.trim(),
    'instructions': instructions.text.trim(),
    'fromAi': fromAi,
  };

  void dispose() {
    for (final c in _all) {
      c.dispose();
    }
  }
}

const _forms = [
  '',
  'tablet',
  'capsule',
  'syrup',
  'suspension',
  'drops',
  'inhaler',
  'injection',
  'cream',
  'gel',
  'ointment',
  'sachet',
  'spray',
]; // fmt: skip

class _ConsultPageState extends State<ConsultPage> {
  Map<String, dynamic>? _visit;
  String? _error;
  bool _busy = false;
  bool _done = false;

  /// The language of the patient's signed report: English unless the
  /// doctor switches it.
  String _language = 'en';

  final _diagnosis = <String>[];
  final _diagnosisInput = TextEditingController();
  final _meds = <_Med>[];
  final _tests = <String>[];
  final _testInput = TextEditingController();
  final _advice = <String>[];
  final _adviceInput = TextEditingController();
  final _followUp = TextEditingController();
  final _notes = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final m in _meds) {
      m.dispose();
    }
    for (final c in [
      _diagnosisInput,
      _testInput,
      _adviceInput,
      _followUp,
      _notes,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final visit =
          await widget.api.get('/visits/${widget.visitId}')
              as Map<String, dynamic>;
      final review = visit['review'] as Map<String, dynamic>?;
      if (!mounted) return;
      setState(() {
        _visit = visit;
        _done = review?['status'] == 'final';
        if (review != null) {
          _diagnosis
            ..clear()
            ..addAll([
              for (final d in review['diagnosis'] as List)
                (d as Map)['name'] as String,
            ]);
          for (final m in _meds) {
            m.dispose();
          }
          _meds
            ..clear()
            ..addAll([
              for (final m in review['medicines'] as List)
                _Med((m as Map).cast<String, dynamic>()),
            ]);
          _tests
            ..clear()
            ..addAll((review['tests'] as List).cast<String>());
          _advice
            ..clear()
            ..addAll((review['advice'] as List).cast<String>());
          _followUp.text = review['followUp'] as String? ?? '';
          _notes.text = review['privateNotes'] as String? ?? '';
        }
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Map<String, dynamic> get _draft => {
    'diagnosis': [
      for (final d in _diagnosis) {'name': d},
    ],
    'medicines': [
      for (final m in _meds)
        if (m.name.text.trim().isNotEmpty) m.toJson(),
    ],
    'tests': _tests,
    'advice': _advice,
    'followUp': _followUp.text.trim(),
    'privateNotes': _notes.text.trim(),
    'language': _language,
  };

  Future<bool> _act(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    var ok = true;
    try {
      await action();
    } on ApiException catch (e) {
      ok = false;
      _error = e.message;
    }
    if (mounted) setState(() => _busy = false);
    return ok;
  }

  Future<void> _save() => _act(() async {
    await widget.api.send(
      'PUT',
      '/visits/${widget.visitId}/draft',
      body: _draft,
    );
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Draft saved.')));
    }
  });

  Future<void> _release() async {
    if (await _act(
      () => widget.api.send('POST', '/visits/${widget.visitId}/release'),
    )) {
      widget.onClose();
    }
  }

  Future<void> _finalize() async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign and send to the patient?'),
        content: Text(
          'The patient receives your diagnosis, ${_meds.length} '
          '${_meds.length == 1 ? 'medicine' : 'medicines'}, tests, advice and '
          'follow-up as their final report in ${languageName(_language)}, '
          'signed with your name and registration number. Your private notes '
          'stay private.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Back'),
          ),
          FilledButton(
            key: const Key('confirm-finalize'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Sign and send'),
          ),
        ],
      ),
    );
    if (sure != true) return;
    if (await _act(
      () => widget.api.send(
        'POST',
        '/visits/${widget.visitId}/finalize',
        body: _draft,
      ),
    )) {
      setState(() => _done = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final visit = _visit;
    if (visit == null) {
      return _error != null
          ? MedoraNotice(icon: Icons.error_outline, message: _error!)
          : const Center(child: CircularProgressIndicator());
    }
    final wide = MediaQuery.sizeOf(context).width >= 1100;
    final left = _MedoraSide(
      visit: visit,
      onDiagnose: _done
          ? null
          : (name) => setState(() {
              if (!_diagnosis.contains(name)) _diagnosis.add(name);
            }),
    );
    final right = _done
        ? _Signed(
            api: widget.api,
            visit: visit,
            language: _language,
            onClose: widget.onClose,
          )
        : _editor(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            TextButton.icon(
              onPressed: widget.onClose,
              icon: const Icon(Icons.arrow_back_rounded),
              label: const Text('Back to queue'),
            ),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                _done ? 'Consultation signed' : 'Consultation in progress',
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
            const Spacer(),
            if (_busy)
              const SizedBox(
                width: 120,
                child: LinearProgressIndicator(minHeight: 3),
              ),
          ],
        ),
        const SizedBox(height: 8),
        if (_error != null) ...[
          MedoraNotice(icon: Icons.error_outline, message: _error!),
          const SizedBox(height: 12),
        ],
        if (wide)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 6, child: left),
              const SizedBox(width: 20),
              Expanded(flex: 5, child: right),
            ],
          )
        else ...[
          left,
          const SizedBox(height: 20),
          right,
        ],
      ],
    );
  }

  Widget _editor(BuildContext context) {
    final text = Theme.of(context).textTheme;
    Widget listEditor({
      required List<String> items,
      required TextEditingController input,
      required String hint,
      required Key key,
    }) => Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final (i, item) in items.indexed)
          Row(
            children: [
              const Icon(Icons.circle, size: 7, color: MedoraColors.primary),
              const SizedBox(width: 10),
              Expanded(child: Text(item)),
              IconButton(
                tooltip: 'Remove',
                onPressed: () => setState(() => items.removeAt(i)),
                icon: const Icon(Icons.close_rounded, size: 18),
              ),
            ],
          ),
        TextField(
          key: key,
          controller: input,
          decoration: InputDecoration(
            hintText: hint,
            suffixIcon: IconButton(
              tooltip: 'Add',
              icon: const Icon(Icons.add_rounded),
              onPressed: () => setState(() {
                if (input.text.trim().isNotEmpty) items.add(input.text.trim());
                input.clear();
              }),
            ),
          ),
          onSubmitted: (value) => setState(() {
            if (value.trim().isNotEmpty) items.add(value.trim());
            input.clear();
          }),
        ),
      ],
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Section(
          icon: Icons.fact_check_outlined,
          color: MedoraColors.accent,
          title: 'Your diagnosis',
          subtitle: 'Tap "Add" beside a Medora condition, or type your own.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final d in _diagnosis)
                    InputChip(
                      label: Text(d),
                      onDeleted: () => setState(() => _diagnosis.remove(d)),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              TextField(
                key: const Key('diagnosis-input'),
                controller: _diagnosisInput,
                decoration: InputDecoration(
                  hintText: 'Add a diagnosis',
                  suffixIcon: IconButton(
                    icon: const Icon(Icons.add_rounded),
                    onPressed: () => setState(() {
                      final v = _diagnosisInput.text.trim();
                      if (v.isNotEmpty && !_diagnosis.contains(v)) {
                        _diagnosis.add(v);
                      }
                      _diagnosisInput.clear();
                    }),
                  ),
                ),
                onSubmitted: (v) => setState(() {
                  if (v.trim().isNotEmpty && !_diagnosis.contains(v.trim())) {
                    _diagnosis.add(v.trim());
                  }
                  _diagnosisInput.clear();
                }),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Section(
          icon: Icons.medication_outlined,
          title: 'Prescription',
          subtitle:
              'Medora\'s suggestions are filled in: check, change or remove each one.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final (i, m) in _meds.indexed) ...[
                _MedEditor(
                  med: m,
                  onRemove: () => setState(() => _meds.removeAt(i).dispose()),
                  onForm: (form) => setState(() => m.form = form),
                ),
                const SizedBox(height: 12),
              ],
              OutlinedButton.icon(
                key: const Key('add-medicine'),
                onPressed: () => setState(() => _meds.add(_Med(const {}))),
                icon: const Icon(Icons.add_rounded),
                label: const Text('Add medicine'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Section(
          icon: Icons.biotech_outlined,
          title: 'Tests',
          child: listEditor(
            items: _tests,
            input: _testInput,
            hint: 'Add a test (e.g. CBC, Dengue NS1)',
            key: const Key('test-input'),
          ),
        ),
        const SizedBox(height: 16),
        Section(
          icon: Icons.tips_and_updates_outlined,
          title: 'Advice for the patient',
          child: listEditor(
            items: _advice,
            input: _adviceInput,
            hint: 'Add advice',
            key: const Key('advice-input'),
          ),
        ),
        const SizedBox(height: 16),
        Section(
          icon: Icons.event_repeat_outlined,
          title: 'Follow-up and notes',
          child: Column(
            children: [
              TextField(
                key: const Key('follow-up'),
                controller: _followUp,
                decoration: const InputDecoration(
                  labelText: 'Follow-up (e.g. review in 3 days)',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _notes,
                minLines: 2,
                maxLines: 5,
                decoration: const InputDecoration(
                  labelText: 'Private notes (never shown to the patient)',
                  alignLabelWithHint: true,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        _SignBar(
          language: _language,
          patientLanguage: '${_visit?['language'] ?? 'en'}',
          onLanguage: _busy ? null : (v) => setState(() => _language = v),
          actions: [
            FilledButton.icon(
              key: const Key('finalize'),
              onPressed: _busy ? null : _finalize,
              icon: const Icon(Icons.verified_outlined),
              label: const Text('Sign and finalise'),
            ),
            OutlinedButton(
              onPressed: _busy ? null : _save,
              child: const Text('Save draft'),
            ),
            TextButton(
              onPressed: _busy ? null : _release,
              child: Text(
                'Return to queue',
                style: text.bodyMedium?.copyWith(color: MedoraColors.accent),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _MedEditor extends StatelessWidget {
  const _MedEditor({
    required this.med,
    required this.onRemove,
    required this.onForm,
  });

  final _Med med;
  final VoidCallback onRemove;
  final ValueChanged<String> onForm;

  @override
  Widget build(BuildContext context) {
    Widget field(TextEditingController c, String label, {double width = 150}) =>
        SizedBox(
          width: width,
          child: TextField(
            controller: c,
            decoration: InputDecoration(labelText: label, isDense: true),
          ),
        );
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: MedoraColors.field,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: MedoraColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: field(med.name, 'Medicine', width: double.infinity),
              ),
              const SizedBox(width: 8),
              if (med.fromAi) const Tag('Medora suggested', MedoraColors.ochre),
              IconButton(
                tooltip: 'Remove',
                onPressed: onRemove,
                icon: const Icon(Icons.delete_outline_rounded),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              SizedBox(
                width: 150,
                child: DropdownButtonFormField<String>(
                  initialValue: _forms.contains(med.form) ? med.form : '',
                  isDense: true,
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: 'Form',
                    isDense: true,
                  ),
                  items: [
                    for (final f in _forms)
                      DropdownMenuItem(
                        value: f,
                        child: Text(f.isEmpty ? '—' : f),
                      ),
                  ],
                  onChanged: (v) => onForm(v ?? ''),
                ),
              ),
              field(med.strength, 'Strength'),
              field(med.dose, 'Dose'),
              field(med.frequency, 'How often', width: 200),
              field(med.duration, 'For how long'),
              field(med.maxDaily, 'Max in 24 h'),
              field(med.route, 'Route', width: 110),
            ],
          ),
          const SizedBox(height: 8),
          TextField(
            controller: med.instructions,
            decoration: const InputDecoration(
              labelText: 'Instructions or caution for the patient',
              isDense: true,
            ),
          ),
        ],
      ),
    );
  }
}

/// The last card: the language of the patient's signed report, and the
/// buttons to sign, save or hand the patient back.
class _SignBar extends StatelessWidget {
  const _SignBar({
    required this.language,
    required this.patientLanguage,
    required this.onLanguage,
    required this.actions,
  });

  final String language;

  /// The language the patient used at the kiosk.
  final String patientLanguage;
  final ValueChanged<String>? onLanguage;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.fromLTRB(22, 20, 22, 20),
      decoration: BoxDecoration(
        color: MedoraColors.primary.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: MedoraColors.primary.withValues(alpha: 0.22)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 16,
            runSpacing: 10,
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.translate_rounded,
                    size: 20,
                    color: MedoraColors.primary,
                  ),
                  const SizedBox(width: 10),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'Patient\'s report language',
                        style: text.titleMedium,
                      ),
                      Text(
                        patientLanguage == 'ml'
                            ? 'The patient spoke Malayalam at the kiosk.'
                            : 'The patient used English at the kiosk.',
                        style: text.bodySmall,
                      ),
                    ],
                  ),
                ],
              ),
              ReportLanguageToggle(value: language, onChanged: onLanguage),
            ],
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: Divider(height: 1),
          ),
          Wrap(spacing: 12, runSpacing: 12, children: actions),
        ],
      ),
    );
  }
}

/// After signing: where the patient's report is, and back to the queue.
class _Signed extends StatelessWidget {
  const _Signed({
    required this.api,
    required this.visit,
    required this.language,
    required this.onClose,
  });

  final DoctorApi api;
  final Map<String, dynamic> visit;
  final String language;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(
            Icons.verified_rounded,
            color: MedoraColors.teal,
            size: 48,
          ),
          const SizedBox(height: 10),
          Text(
            'Signed and sent',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 6),
          Text(
            'The patient\'s final report is ready on their phone (the code from the '
            'kiosk) and as a PDF, in ${languageName(language)}.',
            style: Theme.of(context).textTheme.bodyLarge,
          ),
          const SizedBox(height: 18),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              OutlinedButton.icon(
                onPressed: () =>
                    launchUrl(api.patientPdf(visit['id'] as String)),
                icon: const Icon(Icons.picture_as_pdf_outlined),
                label: const Text('Open signed PDF'),
              ),
              FilledButton(
                onPressed: onClose,
                child: const Text('Next patient'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Medora's side: the patient, what they told, the vitals, the doctor
/// report and the history.
class _MedoraSide extends StatelessWidget {
  const _MedoraSide({required this.visit, required this.onDiagnose});

  final Map<String, dynamic> visit;

  /// Adds a Medora condition to the diagnosis; null once signed.
  final ValueChanged<String>? onDiagnose;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final patient = (visit['patient'] as Map).cast<String, dynamic>();
    final told = (visit['told'] as Map).cast<String, dynamic>();
    final ai = (visit['ai'] as Map).cast<String, dynamic>();
    final vitals = (ai['vitals'] as List? ?? const []).cast<Map>();
    final conditions = (ai['conditions'] as List? ?? const []).cast<Map>();
    final medicines = (ai['medicines'] as List? ?? const []).cast<Map>();
    final notes = (ai['doctorNotes'] as List? ?? const []).cast<String>();
    final sources = (ai['guidelineEvidence'] as List? ?? const []).cast<Map>();
    final history = (visit['history'] as List? ?? const []).cast<Map>();
    final record = visit['record'] as Map?;

    Widget line(String label, Object? value, {Color? color}) {
      final shown = '${value ?? ''}'.trim();
      if (shown.isEmpty) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 160,
              child: Text(
                label,
                style: text.bodyMedium?.copyWith(fontSize: 14),
              ),
            ),
            Expanded(
              child: Text(
                shown,
                style: TextStyle(
                  color: color ?? MedoraColors.text,
                  fontWeight: color == null ? null : FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
      );
    }

    final allergies = '${told['allergies'] ?? ''}'.trim();
    final allergic =
        allergies.isNotEmpty &&
        !{
          'none',
          'no',
          'nil',
          'no known allergies',
        }.contains(allergies.toLowerCase());
    final pregnancy = '${told['pregnancy'] ?? ''}';
    final urgency = ai['urgency'] as String?;
    final color = urgencyColor(urgency);
    final spoke = '${visit['language'] ?? 'en'}';

    Widget fact(IconData icon, String label, Object? value) {
      final shown = '${value ?? ''}'.trim();
      if (shown.isEmpty) return const SizedBox.shrink();
      return SizedBox(
        width: 250,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 17, color: MedoraColors.muted),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: text.bodySmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Text(
                    shown,
                    style: const TextStyle(
                      fontFamilyFallback: MedoraFonts.fallback,
                      color: MedoraColors.text,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        MedoraCard(
          padding: EdgeInsets.zero,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                height: 6,
                decoration: BoxDecoration(
                  color: color,
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(22),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(22, 20, 22, 20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Initials(patient['name'], size: 60, color: color),
                        const SizedBox(width: 16),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${patient['name']}',
                                style: text.headlineSmall,
                              ),
                              const SizedBox(height: 2),
                              Text(
                                [
                                  ageAndSex(patient['age'], patient['gender']),
                                  'Visit ${visit['visitNumber']}',
                                  if (visit['at'] != null) when(visit['at']),
                                ].where((x) => x.isNotEmpty).join('  ·  '),
                                style: text.bodyMedium,
                              ),
                              const SizedBox(height: 8),
                              Wrap(
                                spacing: 8,
                                runSpacing: 6,
                                children: [
                                  UrgencyTag(urgency),
                                  if ('${ai['department'] ?? ''}'.isNotEmpty)
                                    Tag(
                                      '${ai['department']}',
                                      MedoraColors.primary,
                                    ),
                                  if (record != null &&
                                      (record['visits'] as int? ?? 0) > 1)
                                    Tag(
                                      '${record['visits']} visits',
                                      MedoraColors.navy,
                                    ),
                                  Tag(
                                    spoke == 'ml'
                                        ? 'Spoke Malayalam'
                                        : 'Spoke English',
                                    MedoraColors.ochre,
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    if (allergic) ...[
                      const SizedBox(height: 16),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 10,
                        ),
                        decoration: BoxDecoration(
                          color: MedoraColors.danger.withValues(alpha: 0.07),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: MedoraColors.danger.withValues(alpha: 0.3),
                          ),
                        ),
                        child: Row(
                          children: [
                            const Icon(
                              Icons.warning_amber_rounded,
                              color: MedoraColors.danger,
                              size: 20,
                            ),
                            const SizedBox(width: 10),
                            const Text(
                              'Allergy  ',
                              style: TextStyle(
                                color: MedoraColors.danger,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            Expanded(
                              child: Text(
                                allergies,
                                style: const TextStyle(
                                  color: MedoraColors.danger,
                                  fontWeight: FontWeight.w700,
                                  fontFamilyFallback: MedoraFonts.fallback,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                    if (pregnancy == 'yes' || pregnancy == 'unsure') ...[
                      const SizedBox(height: 10),
                      MedoraNotice(
                        icon: Icons.pregnant_woman_rounded,
                        color: MedoraColors.danger,
                        message: pregnancy == 'yes'
                            ? 'She says she could be pregnant.'
                            : 'She is not sure whether she could be pregnant.',
                      ),
                    ],
                    const SizedBox(height: 18),
                    const Divider(height: 1),
                    const SizedBox(height: 16),
                    Wrap(
                      spacing: 18,
                      runSpacing: 14,
                      children: [
                        fact(Icons.phone_outlined, 'Phone', patient['phone']),
                        fact(
                          Icons.monitor_weight_outlined,
                          'Weight',
                          patient['weightKg'] == null
                              ? ''
                              : '${patient['weightKg']} kg',
                        ),
                        if (!allergic)
                          fact(
                            Icons.health_and_safety_outlined,
                            'Allergies',
                            'None stated',
                          ),
                        if (pregnancy == 'no')
                          fact(
                            Icons.pregnant_woman_rounded,
                            'Could be pregnant',
                            'No, she says',
                          ),
                        fact(
                          Icons.monitor_heart_outlined,
                          'Long-term conditions',
                          told['conditions'],
                        ),
                        fact(
                          Icons.medication_liquid_outlined,
                          'Daily medicines',
                          told['regularMedicines'],
                        ),
                        fact(
                          Icons.content_cut_rounded,
                          'Past operations',
                          told['surgeries'],
                        ),
                        fact(
                          Icons.smoking_rooms_outlined,
                          'Smoking / alcohol',
                          told['habits'],
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Section(
          icon: Icons.record_voice_over_outlined,
          color: MedoraColors.accent,
          title: 'What the patient told Medora',
          child: Column(
            children: [
              line('Symptoms', told['symptoms']),
              line('Since', told['duration']),
              line('Medicines taken', told['medicationsTaken']),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (vitals.isNotEmpty) ...[
          Section(
            icon: Icons.favorite_border_rounded,
            color: MedoraColors.teal,
            title: 'Vitals',
            subtitle: 'From the smart band at the kiosk.',
            child: Tiles(
              minWidth: 150,
              children: [for (final v in vitals) VitalTile(vital: v)],
            ),
          ),
          const SizedBox(height: 16),
        ],
        Section(
          icon: Icons.auto_awesome_outlined,
          title: 'Medora\'s assessment',
          subtitle:
              'Suggestions for you to confirm. Sent to: ${ai['department'] ?? '—'}.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if ('${ai['clinicalSummary'] ?? ''}'.isNotEmpty ||
                  '${ai['summary'] ?? ''}'.isNotEmpty)
                Text(
                  '${'${ai['clinicalSummary'] ?? ''}'.isNotEmpty ? ai['clinicalSummary'] : ai['summary']}',
                ),
              if ('${ai['note'] ?? ''}'.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text('${ai['note']}', style: text.bodyMedium),
              ],
              const SizedBox(height: 12),
              Text(
                'Possible conditions (AI estimate)',
                style: text.titleMedium,
              ),
              const SizedBox(height: 8),
              if (conditions.isEmpty)
                Text('None named.', style: text.bodyMedium),
              for (final c in conditions)
                _ConditionRow(condition: c, onAdd: onDiagnose),
              if (medicines.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text('Suggested medicines', style: text.titleMedium),
                const SizedBox(height: 6),
                for (final m in medicines)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Wrap(
                      spacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          [
                            m['name'],
                            m['strength'],
                            m['dose'],
                            m['frequency'],
                            m['duration'],
                          ].where((x) => '${x ?? ''}'.isNotEmpty).join(' · '),
                        ),
                        if (m['doctorOnly'] == true)
                          const Tag('For your decision', MedoraColors.warning),
                        if (m['doseEvidence'] is Map &&
                            '${m['dose'] ?? ''}'.isNotEmpty)
                          (m['doseEvidence'] as Map)['found'] == true
                              ? Tag(
                                  'Dose in ${(m['doseEvidence'] as Map)['source']}',
                                  MedoraColors.teal,
                                )
                              : const Tag(
                                  'Dose not in guidelines',
                                  MedoraColors.warning,
                                ),
                      ],
                    ),
                  ),
              ],
              if (notes.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text('Points to check', style: text.titleMedium),
                for (final n in notes) Text('• $n'),
              ],
            ],
          ),
        ),
        if (sources.isNotEmpty) ...[
          const SizedBox(height: 16),
          Section(
            key: const ValueKey('guideline-sources'),
            icon: Icons.menu_book_outlined,
            color: MedoraColors.ochre,
            title: 'Guideline sources',
            subtitle:
                'Passages Medora read before suggesting (tier 1 = Indian government).',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [for (final g in sources) _SourceRow(source: g)],
            ),
          ),
        ],
        const SizedBox(height: 16),
        Section(
          icon: Icons.history_rounded,
          color: MedoraColors.navy,
          title: 'Earlier visits',
          subtitle: history.isEmpty
              ? 'This is the patient\'s first visit here.'
              : null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final h in history)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(when(h['at']), style: text.titleMedium),
                      Text('Told: ${h['symptoms']}'),
                      if ((h['diagnosis'] as List).isNotEmpty)
                        Text(
                          'Diagnosis by ${h['doctor']}: ${(h['diagnosis'] as List).join(', ')}',
                        ),
                      if ((h['medicines'] as List).isNotEmpty)
                        Text(
                          'Prescribed: ${(h['medicines'] as List).join('; ')}',
                          style: text.bodyMedium,
                        ),
                      if ('${h['followUp'] ?? ''}'.isNotEmpty)
                        Text(
                          'Follow-up: ${h['followUp']}',
                          style: text.bodyMedium,
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

/// One guideline passage: [S1] source, page, where in it, and its opening.
class _SourceRow extends StatelessWidget {
  const _SourceRow({required this.source});

  final Map source;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final excerpt = '${source['excerpt'] ?? ''}'.trim();
    final page = source['page'];
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Tag('${source['label']}', MedoraColors.primary),
              Text(
                '${source['sourceTitle']}${page == null ? '' : ', page $page'}',
                style: text.titleSmall,
              ),
              if (source['productionAllowed'] != true)
                const Tag('Testing only', MedoraColors.warning),
            ],
          ),
          const SizedBox(height: 4),
          Text('${source['breadcrumb']}', style: text.bodyMedium),
          if (excerpt.isNotEmpty)
            Text(
              excerpt.length > 320 ? '${excerpt.substring(0, 320)}…' : excerpt,
              style: text.bodySmall,
            ),
        ],
      ),
    );
  }
}

class _ConditionRow extends StatelessWidget {
  const _ConditionRow({required this.condition, required this.onAdd});

  final Map condition;
  final ValueChanged<String>? onAdd;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final percent = condition['probability'] as int? ?? 0;
    final doubt = '${condition['doubtReason'] ?? ''}';
    final doubted = condition.containsKey('doubtReason');
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${condition['name']}',
                  style: text.titleMedium?.copyWith(
                    color: doubted ? MedoraColors.muted : MedoraColors.text,
                  ),
                ),
              ),
              Text(
                '$percent%',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              if (onAdd != null)
                TextButton(
                  onPressed: () => onAdd!('${condition['name']}'),
                  child: const Text('Add'),
                ),
            ],
          ),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: percent / 100,
              minHeight: 6,
              color: doubted ? MedoraColors.muted : MedoraColors.primary,
              backgroundColor: MedoraColors.border,
            ),
          ),
          if ('${condition['reasoning'] ?? ''}'.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '${condition['reasoning']}',
                style: text.bodyMedium?.copyWith(fontSize: 14),
              ),
            ),
          if (doubted)
            Text(
              'Doubted by Medora\'s check${doubt.isEmpty ? '' : ': $doubt'}',
              style: text.bodyMedium?.copyWith(
                fontSize: 13.5,
                color: MedoraColors.warning,
              ),
            ),
        ],
      ),
    );
  }
}
