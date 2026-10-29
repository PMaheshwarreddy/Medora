import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api/api_client.dart' show ApiException;
import '../../hospital/hospital_widgets.dart';
import '../../theme/medora_theme.dart';
import '../../widgets/medora_scaffold.dart' show MedoraCard, MedoraNotice;
import '../doctor_screen.dart' show DoctorApi;
import '../doctor_widgets.dart';

/// One consultation, as one calm column (the user's request of 2026-10-29:
/// not side by side). On top, the patient; then the case file as rows the
/// doctor opens with a tap (patient details, what they told Medora, vitals,
/// Medora's assessment, earlier visits), each showing its gist while
/// closed; then the doctor's decisions as numbered steps with type-ahead
/// for diagnoses, medicines and tests; and a sign bar that stays at the
/// bottom of the screen and says what is still missing.
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

  bool get isEmpty => name.text.trim().isEmpty;

  /// What signing needs (the server checks the same): a dose and how often.
  bool get complete =>
      dose.text.trim().isNotEmpty && frequency.text.trim().isNotEmpty;

  /// A preparation picked from the suggestions fills these in.
  void pick(Map<String, dynamic> s) {
    name.text = '${s['name'] ?? name.text}';
    if ('${s['strength'] ?? ''}'.isNotEmpty) strength.text = '${s['strength']}';
    if ('${s['form'] ?? ''}'.isNotEmpty) form = '${s['form']}';
    if ('${s['route'] ?? ''}'.isNotEmpty) route.text = '${s['route']}';
  }

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
  'eye drops',
  'ear drops',
  'nasal spray',
  'nasal drops',
  'inhaler',
  'nebuliser solution',
  'injection',
  'cream',
  'gel',
  'ointment',
  'lotion',
  'sachet',
  'powder',
  'spray',
  'sublingual tablet',
  'vaginal tablet',
]; // fmt: skip

/// Quick picks for the prescription's free-text fields.
const _howOften = [
  'Once daily',
  'Twice daily',
  'Three times daily',
  'Every 6 hours if needed',
  'Every 8 hours',
  'At night',
  'Before breakfast',
  'Once only',
]; // fmt: skip
const _howLong = [
  '3 days',
  '5 days',
  '7 days',
  '10 days',
  '2 weeks',
  'Until the fever settles',
  'Continue',
]; // fmt: skip
const _followUps = [
  'Review in 3 days',
  'Review in 1 week',
  'Review with test reports',
  'Come back at once if worse',
  'No follow-up needed',
]; // fmt: skip

/// Answers that mean "nothing to report".
final _nothing = RegExp(
  r'^(none|no|nil|nothing|na|n/a|not applicable|no known( drug)? allergies|'
  r'no allergies?|nkda|not allergic|none known|none reported|ഇല്ല|ഒന്നുമില്ല|'
  r'അലർജി ഇല്ല|അലർജിയില്ല)$',
);

bool _says(Object? value) {
  final v = '${value ?? ''}'.trim().toLowerCase().replaceAll(
    RegExp(r'[.!]+$'),
    '',
  );
  return v.isNotEmpty && !_nothing.hasMatch(v);
}

/// "… consistent with [S3]." -> "… consistent with." (the passages are not
/// shown here any more).
String _uncited(Object? text) => '${text ?? ''}'
    .replaceAll(
      RegExp(
        r'\s*(?:,\s*)?(?:(?:as\s+)?(?:described|noted|stated|given|shown)\s+in|'
        r'consistent with(?: [a-z ]{0,40}? described in)?|according to|per|see|in)?'
        r'\s*\[S\d+(?:\s*[,;]\s*S?\d+)*\]',
        caseSensitive: false,
      ),
      '',
    )
    .replaceAll(RegExp(r'\s+([.,;])'), r'$1')
    .trim();

class _ConsultPageState extends State<ConsultPage> {
  Map<String, dynamic>? _visit;
  String? _error;
  bool _busy = false;
  bool _done = false;

  /// The language of the patient's signed report: English unless the
  /// doctor switches it.
  String _language = 'en';

  /// Which case-file rows are open.
  final _open = <String>{};

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
    _followUp.addListener(_changed);
    _load();
  }

  void _changed() {
    if (mounted) setState(() {});
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

  _Med _newMed(Map<String, dynamic> m) {
    final med = _Med(m);
    // The sign bar follows what is filled in.
    for (final c in [med.name, med.dose, med.frequency]) {
      c.addListener(_changed);
    }
    return med;
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
                _newMed((m as Map).cast<String, dynamic>()),
            ]);
          _tests
            ..clear()
            ..addAll((review['tests'] as List).cast<String>());
          _advice
            ..clear()
            ..addAll(_distinct((review['advice'] as List).cast<String>()));
          _followUp.text = review['followUp'] as String? ?? '';
          _notes.text = review['privateNotes'] as String? ?? '';
        }
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  /// "Avoid strenuous activities." and "Avoid any strenuous activity." are
  /// the same advice: the first is kept.
  static List<String> _distinct(List<String> lines) {
    String key(String s) => s
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-zഀ-ൿ ]'), ' ')
        .split(RegExp(r'\s+'))
        .where((w) => w.isNotEmpty && !{'any', 'all', 'the', 'a'}.contains(w))
        .map(
          (w) => w.length > 3 && w.endsWith('ies')
              ? '${w.substring(0, w.length - 3)}y'
              : w.length > 3 && w.endsWith('s')
              ? w.substring(0, w.length - 1)
              : w,
        )
        .join(' ');
    final seen = <String>{};
    return [
      for (final l in lines)
        if (l.trim().isNotEmpty && seen.add(key(l))) l,
    ];
  }

  Map<String, dynamic> get _draft => {
    'diagnosis': [
      for (final d in _diagnosis) {'name': d},
    ],
    'medicines': [
      for (final m in _meds)
        if (!m.isEmpty) m.toJson(),
    ],
    'tests': _tests,
    'advice': _advice,
    'followUp': _followUp.text.trim(),
    'privateNotes': _notes.text.trim(),
    'language': _language,
  };

  /// What still stands between the doctor and signing.
  List<String> get _missing => [
    if (_diagnosis.isEmpty) 'Add a diagnosis',
    for (final m in _meds)
      if (!m.isEmpty && !m.complete)
        '${m.name.text.trim()}: ${m.dose.text.trim().isEmpty ? 'dose' : 'how often'}',
  ];

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
    final meds = _meds.where((m) => !m.isEmpty).length;
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign and send to the patient?'),
        content: Text(
          'The patient receives your diagnosis, $meds '
          '${meds == 1 ? 'medicine' : 'medicines'}, tests, advice and '
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

  void _addDiagnosis(String name) {
    final v = name.trim();
    if (v.isEmpty) return;
    setState(() {
      if (!_diagnosis.any((d) => d.toLowerCase() == v.toLowerCase())) {
        _diagnosis.add(v);
      }
    });
  }

  /// Puts one of Medora's suggested medicines on the prescription.
  void _useMedicine(Map m) {
    final name = '${m['name'] ?? ''}'.trim();
    if (name.isEmpty || _hasMedicine(name)) return;
    setState(
      () => _meds.add(
        _newMed({
          for (final k in [
            'name',
            'form',
            'strength',
            'dose',
            'route',
            'frequency',
            'duration',
            'maxDaily',
          ])
            k: '${m[k] ?? ''}',
          'instructions': '${m['caution'] ?? ''}',
          'fromAi': true,
        }),
      ),
    );
  }

  bool _hasMedicine(String name) => _meds.any(
    (x) => x.name.text.trim().toLowerCase() == name.trim().toLowerCase(),
  );

  void _toggle(String row) => setState(() {
    if (!_open.remove(row)) _open.add(row);
  });

  @override
  Widget build(BuildContext context) {
    final visit = _visit;
    if (visit == null) {
      return Center(
        child: _error != null
            ? Padding(
                padding: const EdgeInsets.all(28),
                child: MedoraNotice(
                  icon: Icons.error_outline,
                  message: _error!,
                ),
              )
            : const CircularProgressIndicator(),
      );
    }
    final text = Theme.of(context).textTheme;
    final page = SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(28, 22, 28, 40),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 940),
          child: Column(
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
                      _done
                          ? 'Consultation signed'
                          : 'Consultation in progress',
                      overflow: TextOverflow.ellipsis,
                      style: text.bodyMedium,
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
              const SizedBox(height: 10),
              if (_error != null) ...[
                MedoraNotice(icon: Icons.error_outline, message: _error!),
                const SizedBox(height: 12),
              ],
              _PatientHeader(visit: visit),
              const SizedBox(height: 18),
              _caseFile(context, visit),
              const SizedBox(height: 28),
              if (_done)
                _Signed(
                  api: widget.api,
                  visit: visit,
                  language: _language,
                  onClose: widget.onClose,
                )
              else
                _decision(context, visit),
            ],
          ),
        ),
      ),
    );
    if (_done) return page;
    return Column(
      children: [
        Expanded(child: page),
        _SignBar(
          missing: _missing,
          language: _language,
          patientLanguage: '${visit['language'] ?? 'en'}',
          busy: _busy,
          onLanguage: (v) => setState(() => _language = v),
          onSign: _finalize,
          onSave: _save,
          onRelease: _release,
        ),
      ],
    );
  }

  // --- the case file -------------------------------------------------------

  Widget _caseFile(BuildContext context, Map<String, dynamic> visit) {
    final text = Theme.of(context).textTheme;
    final patient = (visit['patient'] as Map).cast<String, dynamic>();
    final told = (visit['told'] as Map).cast<String, dynamic>();
    final ai = (visit['ai'] as Map).cast<String, dynamic>();
    final vitals = (ai['vitals'] as List? ?? const []).cast<Map>();
    final conditions = (ai['conditions'] as List? ?? const []).cast<Map>();
    final medicines = (ai['medicines'] as List? ?? const []).cast<Map>();
    final notes = (ai['doctorNotes'] as List? ?? const []).cast<String>();
    final history = (visit['history'] as List? ?? const []).cast<Map>();
    final pregnancy = '${told['pregnancy'] ?? ''}';

    final off = vitals
        .where((v) => v['status'] == 'low' || v['status'] == 'high')
        .length;

    String gist(List<Object?> parts) => parts
        .map((p) => '${p ?? ''}'.trim())
        .where((p) => p.isNotEmpty)
        .join('  ·  ');

    final details = [
      ('Phone', patient['phone']),
      (
        'Weight',
        patient['weightKg'] == null ? null : '${patient['weightKg']} kg',
      ),
      ('Allergies', _says(told['allergies']) ? told['allergies'] : 'None'),
      ('Long-term conditions', told['conditions']),
      ('Daily medicines', told['regularMedicines']),
      ('Past operations', told['surgeries']),
      ('Smoking / alcohol', told['habits']),
      if (pregnancy.isNotEmpty)
        (
          'Could be pregnant',
          switch (pregnancy) {
            'yes' => 'Yes, she says',
            'unsure' => 'Not sure',
            _ => 'No, she says',
          },
        ),
    ].where((d) => '${d.$2 ?? ''}'.trim().isNotEmpty).toList();

    return MedoraCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(22, 18, 22, 6),
            child: Text(
              'CASE FILE',
              style: text.bodySmall?.copyWith(
                letterSpacing: 1.4,
                fontWeight: FontWeight.w700,
                color: MedoraColors.muted,
              ),
            ),
          ),
          _FoldRow(
            id: 'details',
            icon: Icons.badge_outlined,
            color: MedoraColors.navy,
            title: 'Patient details',
            summary: gist([
              patient['phone'],
              _says(told['allergies']) ? null : 'No allergies',
              _says(told['conditions']) ? told['conditions'] : null,
              _says(told['regularMedicines'])
                  ? 'On ${told['regularMedicines']}'
                  : null,
            ]),
            open: _open.contains('details'),
            onToggle: _toggle,
            child: _Facts(facts: details),
          ),
          _FoldRow(
            id: 'told',
            icon: Icons.record_voice_over_outlined,
            color: MedoraColors.accent,
            title: 'What the patient told Medora',
            summary: gist([told['symptoms'], told['duration']]),
            open: _open.contains('told'),
            onToggle: _toggle,
            child: _Facts(
              facts: [
                ('Symptoms', told['symptoms']),
                ('Since', told['duration']),
                ('Medicines taken', told['medicationsTaken']),
              ].where((d) => '${d.$2 ?? ''}'.trim().isNotEmpty).toList(),
            ),
          ),
          _FoldRow(
            id: 'vitals',
            icon: Icons.favorite_border_rounded,
            color: off > 0 ? MedoraColors.danger : MedoraColors.teal,
            title: 'Vitals',
            badge: vitals.isEmpty
                ? null
                : off > 0
                ? ('$off out of range', MedoraColors.danger)
                : ('All in range', MedoraColors.teal),
            summaryWidget: vitals.isEmpty
                ? null
                : Wrap(
                    spacing: 8,
                    runSpacing: 6,
                    children: [for (final v in vitals) _VitalChip(vital: v)],
                  ),
            summary: vitals.isEmpty ? 'Not measured at the kiosk' : '',
            open: _open.contains('vitals'),
            onToggle: vitals.isEmpty ? null : _toggle,
            child: Tiles(
              minWidth: 170,
              children: [for (final v in vitals) VitalTile(vital: v)],
            ),
          ),
          _FoldRow(
            id: 'assessment',
            icon: Icons.auto_awesome_outlined,
            color: MedoraColors.primary,
            title: 'Medora\'s assessment',
            badge: ai['department'] == null
                ? null
                : ('${ai['department']}', MedoraColors.primary),
            summary: conditions.isEmpty
                ? 'No condition named'
                : gist([
                    for (final c in conditions.take(2))
                      '${c['name']} ${c['probability'] ?? ''}%',
                    if (conditions.length > 2) '+${conditions.length - 2} more',
                  ]),
            open: _open.contains('assessment'),
            onToggle: _toggle,
            child: _Assessment(
              ai: ai,
              conditions: conditions,
              medicines: medicines,
              notes: notes,
              diagnosis: _diagnosis,
              hasMedicine: _hasMedicine,
              onDiagnose: _done ? null : _addDiagnosis,
              onUseMedicine: _done ? null : _useMedicine,
            ),
          ),
          _FoldRow(
            id: 'history',
            icon: Icons.history_rounded,
            color: MedoraColors.ochre,
            title: 'Earlier visits',
            summary: history.isEmpty
                ? 'First visit to this hospital'
                : '${history.length} earlier '
                      '${history.length == 1 ? 'visit' : 'visits'}, last ${when(history.first['at'])}',
            open: _open.contains('history'),
            onToggle: history.isEmpty ? null : _toggle,
            last: true,
            child: _History(history: history),
          ),
        ],
      ),
    );
  }

  // --- the doctor's decisions ------------------------------------------------

  Widget _decision(BuildContext context, Map<String, dynamic> visit) {
    final text = Theme.of(context).textTheme;
    final ai = (visit['ai'] as Map).cast<String, dynamic>();
    final conditions = (ai['conditions'] as List? ?? const []).cast<Map>();
    // Medora's conditions come first in the diagnosis type-ahead.
    final fromMedora = [
      for (final c in conditions)
        {
          'label': '${c['name']}',
          'name': '${c['name']}',
          'note': 'Medora · ${c['probability'] ?? 0}%',
        },
    ];
    final medsDone =
        _meds.where((m) => !m.isEmpty).isNotEmpty &&
        _meds.where((m) => !m.isEmpty).every((m) => m.complete);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Your decision', style: text.headlineSmall),
        const SizedBox(height: 2),
        Text(
          'This becomes the patient\'s signed report. Start typing to see '
          'suggestions.',
          style: text.bodyMedium,
        ),
        const SizedBox(height: 16),
        _Step(
          number: 1,
          title: 'Diagnosis',
          done: _diagnosis.isNotEmpty,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_diagnosis.isNotEmpty) ...[
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
                const SizedBox(height: 12),
              ],
              _TypeAhead(
                fieldKey: const Key('diagnosis-input'),
                controller: _diagnosisInput,
                api: widget.api,
                kind: 'diagnosis',
                local: fromMedora,
                showLocalWhenEmpty: true,
                hint: 'Search a diagnosis, e.g. viral fever, UTI',
                icon: Icons.search_rounded,
                onPicked: (s) {
                  _addDiagnosis('${s['name']}');
                  _diagnosisInput.clear();
                },
                onFreeText: (v) {
                  _addDiagnosis(v);
                  _diagnosisInput.clear();
                },
              ),
              if (conditions.any((c) => !_diagnosis.contains(c['name']))) ...[
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text('From Medora:', style: text.bodySmall),
                    for (final c in conditions)
                      if (!_diagnosis.contains(c['name']))
                        ActionChip(
                          avatar: const Icon(Icons.add_rounded, size: 16),
                          label: Text(
                            '${c['name']}  ${c['probability'] ?? 0}%',
                          ),
                          onPressed: () => _addDiagnosis('${c['name']}'),
                        ),
                  ],
                ),
              ],
            ],
          ),
        ),
        _Step(
          number: 2,
          title: 'Prescription',
          subtitle: _meds.any((m) => m.fromAi)
              ? 'Medora\'s reviewed suggestions are filled in: check, change '
                    'or remove each one.'
              : 'Search a medicine or a brand (e.g. Dolo 650).',
          done: medsDone,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final (i, m) in _meds.indexed) ...[
                _MedCard(
                  key: ObjectKey(m),
                  index: i,
                  med: m,
                  api: widget.api,
                  onRemove: () => setState(() => _meds.removeAt(i).dispose()),
                  onChanged: _changed,
                ),
                const SizedBox(height: 12),
              ],
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  key: const Key('add-medicine'),
                  onPressed: () => setState(() => _meds.add(_newMed(const {}))),
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('Add medicine'),
                ),
              ),
            ],
          ),
        ),
        _Step(
          number: 3,
          title: 'Tests',
          done: _tests.isNotEmpty,
          optional: true,
          child: _ListEditor(
            items: _tests,
            input: _testInput,
            api: widget.api,
            kind: 'test',
            hint: 'Search a test, e.g. CBC, Dengue NS1',
            fieldKey: const Key('test-input'),
            chips: true,
            onChanged: _changed,
          ),
        ),
        _Step(
          number: 4,
          title: 'Advice for the patient',
          done: _advice.isNotEmpty,
          optional: true,
          child: _ListEditor(
            items: _advice,
            input: _adviceInput,
            hint: 'Add advice',
            fieldKey: const Key('advice-input'),
            onChanged: _changed,
          ),
        ),
        _Step(
          number: 5,
          title: 'Follow-up and private notes',
          done: _followUp.text.trim().isNotEmpty,
          optional: true,
          last: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final f in _followUps)
                    ChoiceChip(
                      label: Text(f),
                      selected: _followUp.text.trim() == f,
                      onSelected: (on) => _followUp.text = on ? f : '',
                    ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('follow-up'),
                controller: _followUp,
                decoration: const InputDecoration(
                  labelText: 'Follow-up (or write your own)',
                  prefixIcon: Icon(Icons.event_repeat_outlined),
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
                  prefixIcon: Icon(Icons.lock_outline_rounded),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// --- the patient on top -------------------------------------------------------

class _PatientHeader extends StatelessWidget {
  const _PatientHeader({required this.visit});

  final Map<String, dynamic> visit;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final patient = (visit['patient'] as Map).cast<String, dynamic>();
    final told = (visit['told'] as Map).cast<String, dynamic>();
    final ai = (visit['ai'] as Map).cast<String, dynamic>();
    final record = visit['record'] as Map?;
    final urgency = ai['urgency'] as String?;
    final color = urgencyColor(urgency);
    final allergies = '${told['allergies'] ?? ''}'.trim();
    final pregnancy = '${told['pregnancy'] ?? ''}';
    final spoke = '${visit['language'] ?? 'en'}';

    return MedoraCard(
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
            padding: const EdgeInsets.fromLTRB(22, 18, 22, 20),
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
                          Text('${patient['name']}', style: text.headlineSmall),
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
                if (_says(allergies)) ...[
                  const SizedBox(height: 16),
                  _Alert(
                    icon: Icons.warning_amber_rounded,
                    label: 'Allergy',
                    message: allergies,
                  ),
                ],
                if (pregnancy == 'yes' || pregnancy == 'unsure') ...[
                  const SizedBox(height: 10),
                  _Alert(
                    icon: Icons.pregnant_woman_rounded,
                    label: 'Pregnancy',
                    message: pregnancy == 'yes'
                        ? 'She says she could be pregnant.'
                        : 'She is not sure whether she could be pregnant.',
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Alert extends StatelessWidget {
  const _Alert({
    required this.icon,
    required this.label,
    required this.message,
  });

  final IconData icon;
  final String label;
  final String message;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: MedoraColors.danger.withValues(alpha: 0.07),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: MedoraColors.danger.withValues(alpha: 0.3)),
    ),
    child: Row(
      children: [
        Icon(icon, color: MedoraColors.danger, size: 20),
        const SizedBox(width: 10),
        Text(
          '$label  ',
          style: const TextStyle(
            color: MedoraColors.danger,
            fontWeight: FontWeight.w800,
          ),
        ),
        Expanded(
          child: Text(
            message,
            style: const TextStyle(
              color: MedoraColors.danger,
              fontWeight: FontWeight.w700,
              fontFamilyFallback: MedoraFonts.fallback,
            ),
          ),
        ),
      ],
    ),
  );
}

// --- case-file rows -----------------------------------------------------------

/// One row of the case file: its gist while closed, everything when open.
class _FoldRow extends StatelessWidget {
  const _FoldRow({
    required this.id,
    required this.icon,
    required this.color,
    required this.title,
    required this.open,
    required this.onToggle,
    required this.child,
    this.summary = '',
    this.summaryWidget,
    this.badge,
    this.last = false,
  });

  final String id;
  final IconData icon;
  final Color color;
  final String title;
  final String summary;
  final Widget? summaryWidget;
  final (String, Color)? badge;
  final bool open;

  /// Null: nothing to open (e.g. no vitals were measured).
  final ValueChanged<String>? onToggle;
  final Widget child;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(height: 1),
        InkWell(
          key: Key('fold-$id'),
          onTap: onToggle == null ? null : () => onToggle!(id),
          borderRadius: last && !open
              ? const BorderRadius.vertical(bottom: Radius.circular(22))
              : null,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(22, 16, 16, 16),
            child: Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(icon, size: 20, color: color),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Flexible(
                            child: Text(
                              title,
                              style: text.titleMedium?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          if (badge != null) ...[
                            const SizedBox(width: 10),
                            Tag(badge!.$1, badge!.$2),
                          ],
                        ],
                      ),
                      if (!open && summaryWidget != null) ...[
                        const SizedBox(height: 6),
                        summaryWidget!,
                      ] else if (!open && summary.isNotEmpty) ...[
                        const SizedBox(height: 3),
                        Text(
                          summary,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: text.bodyMedium?.copyWith(
                            fontSize: 14.5,
                            fontFamilyFallback: MedoraFonts.fallback,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                if (onToggle != null)
                  AnimatedRotation(
                    turns: open ? 0.5 : 0,
                    duration: const Duration(milliseconds: 200),
                    child: const Icon(
                      Icons.expand_more_rounded,
                      color: MedoraColors.muted,
                    ),
                  ),
              ],
            ),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOutCubic,
          alignment: Alignment.topCenter,
          child: open
              ? Padding(
                  padding: const EdgeInsets.fromLTRB(76, 0, 22, 20),
                  child: child,
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

/// Label and value pairs, in two columns when there is room.
class _Facts extends StatelessWidget {
  const _Facts({required this.facts});

  final List<(String, Object?)> facts;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    if (facts.isEmpty) {
      return Text('Nothing recorded.', style: text.bodyMedium);
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth >= 560
            ? (constraints.maxWidth - 24) / 2
            : constraints.maxWidth;
        return Wrap(
          spacing: 24,
          runSpacing: 14,
          children: [
            for (final (label, value) in facts)
              SizedBox(
                width: width,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label.toUpperCase(),
                      style: text.bodySmall?.copyWith(
                        letterSpacing: 0.8,
                        fontWeight: FontWeight.w700,
                        color: MedoraColors.muted,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '$value',
                      style: TextStyle(
                        fontSize: 16,
                        fontFamilyFallback: MedoraFonts.fallback,
                        color: _says(value)
                            ? MedoraColors.text
                            : MedoraColors.muted,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }
}

/// A vital as a small chip in the closed Vitals row: "HR 140 ↑".
class _VitalChip extends StatelessWidget {
  const _VitalChip({required this.vital});

  final Map vital;

  @override
  Widget build(BuildContext context) {
    final status = '${vital['status'] ?? ''}';
    final off = status == 'low' || status == 'high';
    final color = off ? MedoraColors.danger : MedoraColors.teal;
    final name = '${vital['name'] ?? ''}';
    final short = switch (name.toLowerCase()) {
      final n when n.contains('heart') => 'HR',
      final n when n.contains('oxygen') || n.contains('spo2') => 'SpO2',
      final n when n.contains('blood pressure') => 'BP',
      final n when n.contains('temp') => 'Temp',
      _ => name,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: off ? 0.1 : 0.07),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: off ? 0.4 : 0.2)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$short ${vital['value']}',
            style: TextStyle(
              fontSize: 13,
              fontWeight: off ? FontWeight.w800 : FontWeight.w600,
              color: off ? MedoraColors.danger : MedoraColors.text,
            ),
          ),
          if (off)
            Icon(
              status == 'high'
                  ? Icons.arrow_upward_rounded
                  : Icons.arrow_downward_rounded,
              size: 14,
              color: MedoraColors.danger,
            ),
        ],
      ),
    );
  }
}

/// Medora's report for the doctor: summary, conditions with the AI's
/// estimate, suggested medicines (one tap puts one on the prescription) and
/// points to check. The guideline passages are not shown (the user's
/// request of 2026-10-29); they stay in the stored report.
class _Assessment extends StatelessWidget {
  const _Assessment({
    required this.ai,
    required this.conditions,
    required this.medicines,
    required this.notes,
    required this.diagnosis,
    required this.hasMedicine,
    required this.onDiagnose,
    required this.onUseMedicine,
  });

  final Map<String, dynamic> ai;
  final List<Map> conditions;
  final List<Map> medicines;
  final List<String> notes;
  final List<String> diagnosis;
  final bool Function(String) hasMedicine;
  final ValueChanged<String>? onDiagnose;
  final ValueChanged<Map>? onUseMedicine;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final summary = _uncited(
      '${ai['clinicalSummary'] ?? ''}'.isNotEmpty
          ? ai['clinicalSummary']
          : ai['summary'],
    );
    Widget heading(String title) => Padding(
      padding: const EdgeInsets.only(top: 18, bottom: 8),
      child: Text(
        title.toUpperCase(),
        style: text.bodySmall?.copyWith(
          letterSpacing: 1,
          fontWeight: FontWeight.w700,
          color: MedoraColors.muted,
        ),
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (summary.isNotEmpty)
          Text(summary, style: text.bodyLarge?.copyWith(height: 1.5)),
        if ('${ai['note'] ?? ''}'.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('${ai['note']}', style: text.bodyMedium),
        ],
        heading('Possible conditions (AI estimate)'),
        if (conditions.isEmpty) Text('None named.', style: text.bodyMedium),
        for (final c in conditions)
          _ConditionRow(
            condition: c,
            added: diagnosis.contains(c['name']),
            onAdd: onDiagnose,
          ),
        if (medicines.isNotEmpty) ...[
          heading('Suggested medicines'),
          for (final m in medicines)
            _SuggestedMedicine(
              medicine: m,
              added: hasMedicine('${m['name'] ?? ''}'),
              onUse: onUseMedicine,
            ),
        ],
        if (notes.isNotEmpty) ...[
          heading('Points to check'),
          for (final n in notes)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 3),
                    child: Icon(
                      Icons.check_box_outline_blank_rounded,
                      size: 17,
                      color: MedoraColors.primary,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(child: Text(_uncited(n))),
                ],
              ),
            ),
        ],
      ],
    );
  }
}

class _ConditionRow extends StatelessWidget {
  const _ConditionRow({
    required this.condition,
    required this.added,
    required this.onAdd,
  });

  final Map condition;
  final bool added;
  final ValueChanged<String>? onAdd;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final percent = (condition['probability'] as num?)?.round() ?? 0;
    final doubt = '${condition['doubtReason'] ?? ''}';
    final doubted = condition.containsKey('doubtReason');
    final reasoning = _uncited(condition['reasoning']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
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
                style: const TextStyle(
                  fontFamily: MedoraFonts.serif,
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(width: 8),
              if (onAdd != null)
                added
                    ? const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 12),
                        child: Icon(
                          Icons.check_circle_rounded,
                          color: MedoraColors.teal,
                          size: 20,
                        ),
                      )
                    : TextButton(
                        onPressed: () => onAdd!('${condition['name']}'),
                        child: const Text('Add'),
                      ),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: percent / 100,
              minHeight: 6,
              color: doubted ? MedoraColors.muted : MedoraColors.primary,
              backgroundColor: MedoraColors.border,
            ),
          ),
          if (reasoning.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                reasoning,
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

class _SuggestedMedicine extends StatelessWidget {
  const _SuggestedMedicine({
    required this.medicine,
    required this.added,
    required this.onUse,
  });

  final Map medicine;
  final bool added;
  final ValueChanged<Map>? onUse;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final m = medicine;
    final evidence = m['doseEvidence'];
    final source = evidence is Map
        ? _uncited('${evidence['source'] ?? ''}')
        : '';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
      decoration: BoxDecoration(
        color: MedoraColors.field,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: MedoraColors.border),
      ),
      child: Row(
        children: [
          const Icon(Icons.medication_outlined, color: MedoraColors.primary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  [
                    m['name'],
                    m['strength'],
                  ].where((x) => '${x ?? ''}'.isNotEmpty).join(' '),
                  style: text.titleMedium,
                ),
                Text(
                  [
                    m['dose'],
                    m['frequency'],
                    m['duration'],
                  ].where((x) => '${x ?? ''}'.isNotEmpty).join(' · '),
                  style: text.bodyMedium?.copyWith(fontSize: 14),
                ),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: [
                    if (m['doctorOnly'] == true)
                      const Tag('For your decision', MedoraColors.warning),
                    if (evidence is Map && '${m['dose'] ?? ''}'.isNotEmpty)
                      evidence['found'] == true
                          ? Tag('Dose in $source', MedoraColors.teal)
                          : const Tag(
                              'Dose not in guidelines',
                              MedoraColors.warning,
                            ),
                  ],
                ),
              ],
            ),
          ),
          if (onUse != null)
            added
                ? const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12),
                    child: Tooltip(
                      message: 'On the prescription',
                      child: Icon(
                        Icons.check_circle_rounded,
                        color: MedoraColors.teal,
                      ),
                    ),
                  )
                : TextButton.icon(
                    onPressed: () => onUse!(m),
                    icon: const Icon(Icons.add_rounded, size: 18),
                    label: const Text('Prescribe'),
                  ),
        ],
      ),
    );
  }
}

class _History extends StatelessWidget {
  const _History({required this.history});

  final List<Map> history;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final h in history)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
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
                  Text('Follow-up: ${h['followUp']}', style: text.bodyMedium),
              ],
            ),
          ),
      ],
    );
  }
}

// --- the doctor's steps ---------------------------------------------------------

/// One numbered step of the decision, with a line down to the next one.
class _Step extends StatelessWidget {
  const _Step({
    required this.number,
    required this.title,
    required this.child,
    required this.done,
    this.subtitle,
    this.optional = false,
    this.last = false,
  });

  final int number;
  final String title;
  final String? subtitle;
  final Widget child;
  final bool done;
  final bool optional;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final color = done ? MedoraColors.teal : MedoraColors.primary;
    // A Stack, not IntrinsicHeight: the cards hold LayoutBuilders, which
    // cannot report intrinsic sizes. The line runs behind the number.
    return Stack(
      children: [
        if (!last)
          const Positioned(
            left: 21,
            top: 40,
            bottom: 6,
            child: SizedBox(
              width: 1.6,
              child: ColoredBox(color: MedoraColors.border),
            ),
          ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 44,
              child: Align(
                alignment: Alignment.topCenter,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  width: 34,
                  height: 34,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: done ? color : MedoraColors.surface,
                    border: Border.all(color: color, width: 1.6),
                  ),
                  child: done
                      ? const Icon(
                          Icons.check_rounded,
                          size: 18,
                          color: Colors.white,
                        )
                      : Text(
                          '$number',
                          style: TextStyle(
                            fontFamily: MedoraFonts.serif,
                            fontWeight: FontWeight.w700,
                            color: color,
                          ),
                        ),
                ),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Padding(
                padding: EdgeInsets.only(bottom: last ? 0 : 22),
                child: MedoraCard(
                  padding: const EdgeInsets.fromLTRB(22, 18, 22, 22),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Flexible(
                            child: Text(
                              title,
                              style: text.titleLarge?.copyWith(height: 1.2),
                            ),
                          ),
                          if (optional) ...[
                            const SizedBox(width: 10),
                            Text('optional', style: text.bodySmall),
                          ],
                        ],
                      ),
                      if (subtitle != null) ...[
                        const SizedBox(height: 2),
                        Text(
                          subtitle!,
                          style: text.bodyMedium?.copyWith(fontSize: 14),
                        ),
                      ],
                      const SizedBox(height: 14),
                      child,
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// A list the doctor builds: tests as chips, advice as lines, each with a
/// type-ahead or a plain field to add more.
class _ListEditor extends StatelessWidget {
  const _ListEditor({
    required this.items,
    required this.input,
    required this.hint,
    required this.fieldKey,
    required this.onChanged,
    this.api,
    this.kind,
    this.chips = false,
  });

  final List<String> items;
  final TextEditingController input;
  final String hint;
  final Key fieldKey;
  final VoidCallback onChanged;
  final DoctorApi? api;
  final String? kind;
  final bool chips;

  void _add(String value) {
    final v = value.trim();
    if (v.isNotEmpty && !items.any((i) => i.toLowerCase() == v.toLowerCase())) {
      items.add(v);
    }
    input.clear();
    onChanged();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (items.isNotEmpty) ...[
          if (chips)
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final (i, item) in items.indexed)
                  InputChip(
                    label: Text(item),
                    onDeleted: () {
                      items.removeAt(i);
                      onChanged();
                    },
                  ),
              ],
            )
          else
            for (final (i, item) in items.indexed)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Row(
                  children: [
                    const Icon(
                      Icons.check_rounded,
                      size: 18,
                      color: MedoraColors.teal,
                    ),
                    const SizedBox(width: 10),
                    Expanded(child: Text(item)),
                    IconButton(
                      tooltip: 'Remove',
                      onPressed: () {
                        items.removeAt(i);
                        onChanged();
                      },
                      icon: const Icon(Icons.close_rounded, size: 18),
                    ),
                  ],
                ),
              ),
          const SizedBox(height: 10),
        ],
        _TypeAhead(
          fieldKey: fieldKey,
          controller: input,
          api: api,
          kind: kind,
          hint: hint,
          icon: kind == null
              ? Icons.add_comment_outlined
              : Icons.search_rounded,
          onPicked: (s) => _add('${s['name']}'),
          onFreeText: _add,
        ),
      ],
    );
  }
}

/// One medicine of the prescription, laid out wide so nothing is cut off.
class _MedCard extends StatelessWidget {
  const _MedCard({
    super.key,
    required this.index,
    required this.med,
    required this.api,
    required this.onRemove,
    required this.onChanged,
  });

  final int index;
  final _Med med;
  final DoctorApi api;
  final VoidCallback onRemove;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final incomplete = !med.isEmpty && !med.complete;
    Widget field(TextEditingController c, String label, {IconData? icon}) =>
        TextField(
          controller: c,
          decoration: InputDecoration(
            labelText: label,
            isDense: true,
            prefixIcon: icon == null ? null : Icon(icon, size: 18),
          ),
        );
    Widget quick(TextEditingController c, String label, List<String> options) =>
        _TypeAhead(
          controller: c,
          hint: label,
          label: label,
          dense: true,
          local: [
            for (final o in options) {'label': o, 'name': o},
          ],
          showLocalWhenEmpty: true,
          onPicked: (s) {
            c.text = '${s['name']}';
            onChanged();
          },
        );
    final form = DropdownButtonFormField<String>(
      key: ValueKey('form-${med.form}'),
      initialValue: _forms.contains(med.form) ? med.form : '',
      isDense: true,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'Form', isDense: true),
      items: [
        for (final f in _forms)
          DropdownMenuItem(value: f, child: Text(f.isEmpty ? '—' : f)),
      ],
      onChanged: (v) {
        med.form = v ?? '';
        onChanged();
      },
    );
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      padding: const EdgeInsets.fromLTRB(16, 14, 8, 16),
      decoration: BoxDecoration(
        color: MedoraColors.field,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: incomplete
              ? MedoraColors.warning.withValues(alpha: 0.6)
              : MedoraColors.border,
          width: incomplete ? 1.4 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: _TypeAhead(
                  fieldKey: Key('med-name-$index'),
                  controller: med.name,
                  api: api,
                  kind: 'medicine',
                  label: 'Medicine',
                  hint: 'Search a medicine or brand',
                  icon: Icons.medication_outlined,
                  onPicked: (s) {
                    med.pick(s);
                    onChanged();
                  },
                ),
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
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth >= 640 ? 3 : 2;
                final width =
                    (constraints.maxWidth - 12 * (columns - 1)) / columns;
                final cells = [
                  form,
                  field(med.strength, 'Strength'),
                  field(med.dose, 'Dose (e.g. 1 tablet)'),
                  quick(med.frequency, 'How often', _howOften),
                  quick(med.duration, 'For how long', _howLong),
                  field(med.maxDaily, 'Max in 24 h'),
                  field(med.route, 'Route'),
                ];
                return Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    for (final c in cells) SizedBox(width: width, child: c),
                  ],
                );
              },
            ),
          ),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: field(
              med.instructions,
              'Instructions or caution for the patient',
              icon: Icons.info_outline_rounded,
            ),
          ),
          if (incomplete) ...[
            const SizedBox(height: 8),
            Text(
              'Add the dose and how often to sign.',
              style: TextStyle(
                color: MedoraColors.warning,
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// --- type-ahead -----------------------------------------------------------------

/// A field that suggests as the doctor types, like a search box: its own
/// [local] options first (Medora's conditions, quick picks), then the
/// server's (`/api/doctor/suggest`: medicines with strength and form,
/// brands, diagnoses, tests). Enter with nothing highlighted keeps what was
/// typed ([onFreeText]).
class _TypeAhead extends StatefulWidget {
  const _TypeAhead({
    required this.controller,
    required this.hint,
    required this.onPicked,
    this.fieldKey,
    this.onFreeText,
    this.api,
    this.kind,
    this.local = const [],
    this.showLocalWhenEmpty = false,
    this.label,
    this.icon,
    this.dense = false,
  });

  final Key? fieldKey;
  final TextEditingController controller;
  final String hint;
  final String? label;
  final IconData? icon;
  final bool dense;
  final ValueChanged<Map<String, dynamic>> onPicked;
  final ValueChanged<String>? onFreeText;
  final DoctorApi? api;
  final String? kind;
  final List<Map<String, dynamic>> local;
  final bool showLocalWhenEmpty;

  @override
  State<_TypeAhead> createState() => _TypeAheadState();
}

class _TypeAheadState extends State<_TypeAhead> {
  final _focus = FocusNode();
  List<Map<String, dynamic>> _last = const [];

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  Future<List<Map<String, dynamic>>> _options(TextEditingValue value) async {
    final q = value.text.trim();
    final lower = q.toLowerCase();
    final local = [
      for (final o in widget.local)
        if ((q.isEmpty && widget.showLocalWhenEmpty) ||
            (q.isNotEmpty &&
                '${o['label']}'.toLowerCase().contains(lower) &&
                '${o['label']}'.toLowerCase() != lower))
          o,
    ];
    if (widget.kind == null || widget.api == null || q.length < 2) {
      return _last = local;
    }
    // Wait for a pause in typing before asking the server.
    await Future<void>.delayed(const Duration(milliseconds: 180));
    if (widget.controller.text.trim() != q) return _last;
    var remote = <Map<String, dynamic>>[];
    try {
      final found = await widget.api!.get(
        '/suggest',
        query: {'kind': widget.kind!, 'q': q},
      );
      remote = [
        for (final r in found as List) (r as Map).cast<String, dynamic>(),
      ];
    } on ApiException {
      // No suggestions: the doctor types it in full.
    } catch (_) {}
    final seen = {for (final o in local) '${o['label']}'.toLowerCase()};
    return _last = [
      ...local,
      for (final r in remote)
        if (seen.add('${r['label']}'.toLowerCase()) &&
            '${r['label']}'.toLowerCase() != lower)
          r,
    ];
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => RawAutocomplete<Map<String, dynamic>>(
        textEditingController: widget.controller,
        focusNode: _focus,
        displayStringForOption: (o) => '${o['name']}',
        optionsBuilder: _options,
        onSelected: widget.onPicked,
        fieldViewBuilder: (context, controller, focus, submit) => TextField(
          key: widget.fieldKey,
          controller: controller,
          focusNode: focus,
          decoration: InputDecoration(
            labelText: widget.label,
            hintText: widget.hint,
            isDense: widget.dense,
            prefixIcon: widget.icon == null
                ? null
                : Icon(widget.icon, size: 20),
            suffixIcon: widget.onFreeText == null
                ? null
                : IconButton(
                    tooltip: 'Add',
                    icon: const Icon(Icons.add_rounded),
                    onPressed: () => widget.onFreeText!(controller.text),
                  ),
          ),
          onSubmitted: (v) {
            if (_last.isNotEmpty && v.trim().isNotEmpty) {
              submit(); // takes the highlighted suggestion
            } else {
              widget.onFreeText?.call(v);
            }
          },
        ),
        optionsViewBuilder: (context, onSelected, options) => Align(
          alignment: Alignment.topLeft,
          child: Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Material(
              elevation: 3,
              shadowColor: Colors.black26,
              color: MedoraColors.surface,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
                side: const BorderSide(color: MedoraColors.border),
              ),
              clipBehavior: Clip.antiAlias,
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: 340,
                  maxWidth: constraints.maxWidth,
                  minWidth: constraints.maxWidth,
                ),
                child: ListView.builder(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  shrinkWrap: true,
                  itemCount: options.length,
                  itemBuilder: (context, i) {
                    final o = options.elementAt(i);
                    final highlighted =
                        AutocompleteHighlightedOption.of(context) == i;
                    return _OptionTile(
                      option: o,
                      highlighted: highlighted,
                      onTap: () => onSelected(o),
                    );
                  },
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _OptionTile extends StatelessWidget {
  const _OptionTile({
    required this.option,
    required this.highlighted,
    required this.onTap,
  });

  final Map<String, dynamic> option;
  final bool highlighted;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final source = '${option['source'] ?? ''}';
    final note = '${option['note'] ?? ''}'.isNotEmpty
        ? '${option['note']}'
        : switch (source) {
            'brand' => 'Brand',
            'guidelines' => 'From the guidelines',
            _ => '',
          };
    final (icon, color) = switch (source) {
      'brand' => (Icons.local_offer_outlined, MedoraColors.ochre),
      'guidelines' => (Icons.menu_book_outlined, MedoraColors.navy),
      _ when '${option['note'] ?? ''}'.startsWith('Medora') => (
        Icons.auto_awesome_outlined,
        MedoraColors.accent,
      ),
      _ when option.containsKey('form') => (
        Icons.medication_outlined,
        MedoraColors.primary,
      ),
      _ => (Icons.north_west_rounded, MedoraColors.muted),
    };
    return InkWell(
      onTap: onTap,
      child: Container(
        color: highlighted
            ? MedoraColors.primary.withValues(alpha: 0.07)
            : null,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        child: Row(
          children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                '${option['label']}',
                style: const TextStyle(
                  fontSize: 15,
                  color: MedoraColors.text,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            if (note.isNotEmpty) ...[
              const SizedBox(width: 10),
              Text(
                note,
                style: const TextStyle(
                  fontSize: 12.5,
                  color: MedoraColors.muted,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// --- signing ----------------------------------------------------------------------

/// Stays at the bottom of the screen: what is still missing, the language
/// of the patient's report, and the buttons.
class _SignBar extends StatelessWidget {
  const _SignBar({
    required this.missing,
    required this.language,
    required this.patientLanguage,
    required this.busy,
    required this.onLanguage,
    required this.onSign,
    required this.onSave,
    required this.onRelease,
  });

  final List<String> missing;
  final String language;
  final String patientLanguage;
  final bool busy;
  final ValueChanged<String> onLanguage;
  final VoidCallback onSign;
  final VoidCallback onSave;
  final VoidCallback onRelease;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final ready = missing.isEmpty;
    final status = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          ready ? Icons.verified_rounded : Icons.pending_outlined,
          color: ready ? MedoraColors.teal : MedoraColors.warning,
        ),
        const SizedBox(width: 10),
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                ready ? 'Ready to sign' : 'Before you sign',
                style: text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
              Text(
                key: const Key('sign-missing'),
                ready
                    ? 'Report in ${languageName(language)} · the patient used '
                          '${languageName(patientLanguage)}'
                    : missing.join('  ·  '),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: text.bodySmall,
              ),
            ],
          ),
        ),
      ],
    );
    final buttons = <Widget>[
      ReportLanguageToggle(
        value: language,
        onChanged: busy ? null : onLanguage,
      ),
      TextButton(
        onPressed: busy ? null : onRelease,
        child: const Text(
          'Return to queue',
          style: TextStyle(color: MedoraColors.accent),
        ),
      ),
      OutlinedButton(
        onPressed: busy ? null : onSave,
        child: const Text('Save draft'),
      ),
      FilledButton.icon(
        key: const Key('finalize'),
        onPressed: busy || !ready ? null : onSign,
        icon: const Icon(Icons.draw_outlined),
        label: const Text('Sign and finalise'),
      ),
    ];
    return Container(
      decoration: BoxDecoration(
        color: MedoraColors.surface,
        border: const Border(top: BorderSide(color: MedoraColors.border)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.06),
            blurRadius: 18,
            offset: const Offset(0, -4),
          ),
        ],
      ),
      padding: const EdgeInsets.fromLTRB(28, 14, 28, 14),
      child: SafeArea(
        top: false,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1180),
            child: LayoutBuilder(
              builder: (context, constraints) => constraints.maxWidth >= 1000
                  ? Row(
                      children: [
                        Expanded(child: status),
                        const SizedBox(width: 16),
                        // Never overflows: shrinks a little when space is tight.
                        Flexible(
                          flex: 3,
                          child: FittedBox(
                            fit: BoxFit.scaleDown,
                            alignment: Alignment.centerRight,
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                for (final (i, b) in buttons.indexed) ...[
                                  if (i > 0) const SizedBox(width: 10),
                                  b,
                                ],
                              ],
                            ),
                          ),
                        ),
                      ],
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        status,
                        const SizedBox(height: 10),
                        Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: buttons,
                        ),
                      ],
                    ),
            ),
          ),
        ),
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
