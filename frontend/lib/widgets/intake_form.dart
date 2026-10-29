import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/strings.dart';
import '../models/intake.dart';
import '../theme/medora_theme.dart';
import 'medora_scaffold.dart';
import 'suggestion_terms.dart';

/// Patient details, symptoms and medications. Used for manual entry and for
/// the review step, where [flagMissing] marks required fields left empty.
class IntakeForm extends StatefulWidget {
  const IntakeForm({
    super.key,
    required this.initial,
    required this.submitLabel,
    required this.onSubmit,
    this.flagMissing = false,
  });

  final PatientIntake initial;
  final String submitLabel;
  final ValueChanged<PatientIntake> onSubmit;
  final bool flagMissing;

  @override
  State<IntakeForm> createState() => _IntakeFormState();
}

class _IntakeFormState extends State<IntakeForm> {
  final _formKey = GlobalKey<FormState>();
  late final _name = TextEditingController(text: widget.initial.name);
  late final _age = TextEditingController(
    text: widget.initial.age?.toString() ?? '',
  );
  late final _phone = TextEditingController(text: widget.initial.phone);
  late final _email = TextEditingController(text: widget.initial.email);
  late final _symptoms = TextEditingController(text: widget.initial.symptoms);
  late final _duration = TextEditingController(text: widget.initial.duration);
  late final _medications = TextEditingController(
    text: widget.initial.medications,
  );
  late final _allergies = TextEditingController(text: widget.initial.allergies);
  late final _conditions = TextEditingController(
    text: widget.initial.conditions,
  );
  late final _regular = TextEditingController(
    text: widget.initial.regularMedicines,
  );
  late final _surgeries = TextEditingController(text: widget.initial.surgeries);
  late final _habits = TextEditingController(text: widget.initial.habits);
  late final _weight = TextEditingController(
    text: widget.initial.weightKg == null
        ? ''
        : widget.initial.weightKg!.toStringAsFixed(
            widget.initial.weightKg! % 1 == 0 ? 0 : 1,
          ),
  );
  late Gender? _gender = widget.initial.gender;
  // Only shown when the voice agent asked (a complaint where it matters).
  late String _pregnancy = widget.initial.pregnancy;
  late bool _showErrors = widget.flagMissing;

  @override
  void dispose() {
    for (final c in [
      _name,
      _age,
      _phone,
      _email,
      _symptoms,
      _duration,
      _medications,
      _allergies,
      _conditions,
      _regular,
      _surgeries,
      _habits,
      _weight,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    // The suggestion chips show what the text fields already contain.
    for (final c in [
      _symptoms,
      _duration,
      _medications,
      _allergies,
      _conditions,
    ]) {
      c.addListener(_refresh);
    }
  }

  void _refresh() => setState(() {});

  static List<String> _items(TextEditingController c) => [
    for (final part in c.text.split(','))
      if (part.trim().isNotEmpty) part.trim(),
  ];

  /// Whether the field already says [phrase]: as one of its items, or in
  /// the patient's own words ([terms], see suggestion_terms.dart), so what
  /// the voice agent heard lights up the same chips as a tap would.
  static bool _has(
    TextEditingController c,
    String phrase, [
    List<String> terms = const [],
  ]) => _items(c).any(
    (item) =>
        item.toLowerCase() == phrase.toLowerCase() ||
        mentions(item, [phrase, ...terms]),
  );

  /// Adds [phrase] to a comma-separated field, or removes every item that
  /// says it. [exclusive] is an answer that cannot stand beside others
  /// ("None").
  void _toggle(
    TextEditingController c,
    String phrase, {
    List<String> terms = const [],
    String? exclusive,
    List<String> exclusiveTerms = const [],
  }) {
    bool says(String item, String p, List<String> t) =>
        item.toLowerCase() == p.toLowerCase() || mentions(item, [p, ...t]);
    final items = _items(c);
    if (_has(c, phrase, terms)) {
      items.removeWhere((i) => says(i, phrase, terms));
    } else if (phrase == exclusive) {
      items
        ..clear()
        ..add(phrase);
    } else {
      if (exclusive != null) {
        items.removeWhere((i) => says(i, exclusive, exclusiveTerms));
      }
      items.add(phrase);
    }
    c.text = items.join(', ');
  }

  String? _required(String? v, String message) =>
      (v == null || v.trim().isEmpty) ? message : null;

  String? _validateAge(String? v, S s) {
    final age = int.tryParse(v?.trim() ?? '');
    if (age == null) return s.enterAge;
    if (age > 120) return s.validAge;
    return null;
  }

  String? _validatePhone(String? v, S s) {
    final digits = (v ?? '').replaceAll(RegExp(r'[^0-9]'), '');
    if (digits.isEmpty) return s.enterPhone;
    if (digits.length < 7 || digits.length > 15) return s.validPhone;
    return null;
  }

  String? _validateEmail(String? v, S s) {
    final email = v?.trim() ?? '';
    if (email.isEmpty) return null;
    return RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(email)
        ? null
        : s.validEmail;
  }

  void _submit() {
    setState(() => _showErrors = true);
    if (!_formKey.currentState!.validate() || _gender == null) return;
    widget.onSubmit(
      PatientIntake(
        name: _name.text.trim(),
        age: int.parse(_age.text.trim()),
        gender: _gender,
        phone: _phone.text.trim(),
        email: _email.text.trim(),
        symptoms: _symptoms.text.trim(),
        duration: _duration.text.trim(),
        medications: _medications.text.trim(),
        allergies: _allergies.text.trim(),
        conditions: _conditions.text.trim(),
        regularMedicines: _regular.text.trim(),
        surgeries: _surgeries.text.trim(),
        habits: _habits.text.trim(),
        weightKg: double.tryParse(_weight.text.trim().replaceAll(',', '.')),
        patientId: widget.initial.patientId,
        pregnancy: _pregnancy,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return Form(
      key: _formKey,
      autovalidateMode: _showErrors
          ? AutovalidateMode.always
          : AutovalidateMode.disabled,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Section(
            number: 1,
            icon: Icons.person_rounded,
            color: MedoraColors.primary,
            title: s.aboutYou,
            subtitle: s.aboutYouSubtitle,
            children: [
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                decoration: InputDecoration(
                  labelText: s.fullName,
                  prefixIcon: const Icon(Icons.badge_outlined),
                ),
                validator: (v) => _required(v, s.enterName),
              ),
              _FieldRow(
                children: [
                  TextFormField(
                    controller: _age,
                    keyboardType: TextInputType.number,
                    inputFormatters: [
                      FilteringTextInputFormatter.digitsOnly,
                      LengthLimitingTextInputFormatter(3),
                    ],
                    decoration: InputDecoration(
                      labelText: s.age,
                      prefixIcon: const Icon(Icons.cake_outlined),
                    ),
                    validator: (v) => _validateAge(v, s),
                  ),
                  TextFormField(
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    decoration: InputDecoration(
                      labelText: s.phone,
                      prefixIcon: const Icon(Icons.phone_outlined),
                    ),
                    validator: (v) => _validatePhone(v, s),
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Prompt(s.gender),
                  Row(
                    children: [
                      for (final (i, (value, icon)) in const [
                        (Gender.male, Icons.male_rounded),
                        (Gender.female, Icons.female_rounded),
                        (Gender.other, Icons.person_outline_rounded),
                      ].indexed) ...[
                        if (i > 0) const SizedBox(width: 12),
                        Expanded(
                          child: _Choice(
                            label: s.genderName(value.name),
                            icon: icon,
                            selected: _gender == value,
                            expand: true,
                            onTap: () => setState(
                              () => _gender = _gender == value ? null : value,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  if (_showErrors && _gender == null)
                    Padding(
                      padding: const EdgeInsets.only(top: 6, left: 4),
                      child: Text(
                        s.selectGender,
                        style: const TextStyle(
                          color: MedoraColors.warning,
                          fontSize: 14,
                        ),
                      ),
                    ),
                ],
              ),
              TextFormField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: InputDecoration(
                  labelText: s.emailOptional,
                  prefixIcon: const Icon(Icons.mail_outline_rounded),
                ),
                validator: (v) => _validateEmail(v, s),
              ),
            ],
          ),
          const SizedBox(height: 20),
          _Section(
            number: 2,
            icon: Icons.sick_rounded,
            color: MedoraColors.violet,
            title: s.bothering,
            subtitle: s.botheringSubtitle,
            children: [
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  for (final (i, (label, icon)) in _zip(
                    s.symptomSuggestions,
                    symptomIcons,
                  ).indexed)
                    _Choice(
                      label: label,
                      icon: icon,
                      selected: _has(_symptoms, label, symptomTerms[i]),
                      onTap: () =>
                          _toggle(_symptoms, label, terms: symptomTerms[i]),
                    ),
                ],
              ),
              TextFormField(
                controller: _symptoms,
                minLines: 2,
                maxLines: 6,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: s.feelingLabel,
                  hintText: s.feelingHint,
                  alignLabelWithHint: true,
                ),
                validator: (v) => _required(v, s.describeSymptoms),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Prompt(s.sinceWhen),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final label in s.durationSuggestions)
                        _Choice(
                          label: label,
                          selected:
                              _duration.text.trim().toLowerCase() ==
                              label.toLowerCase(),
                          onTap: () => _duration.text =
                              _duration.text.trim().toLowerCase() ==
                                  label.toLowerCase()
                              ? ''
                              : label,
                        ),
                    ],
                  ),
                ],
              ),
              TextFormField(
                controller: _duration,
                decoration: InputDecoration(
                  labelText: s.durationLabel,
                  hintText: s.durationHint,
                  prefixIcon: const Icon(Icons.schedule_rounded),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          _Section(
            number: 3,
            icon: Icons.medication_rounded,
            color: MedoraColors.teal,
            title: s.medication,
            subtitle: s.medicationSubtitle,
            children: [
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  for (final (i, label) in s.medicationSuggestions.indexed)
                    _Choice(
                      label: label,
                      selected: _has(_medications, label, medicationTerms[i]),
                      onTap: () => _toggle(
                        _medications,
                        label,
                        terms: medicationTerms[i],
                        exclusive: s.medicationSuggestions.first,
                        exclusiveTerms: medicationTerms.first,
                      ),
                    ),
                ],
              ),
              TextFormField(
                controller: _medications,
                minLines: 1,
                maxLines: 4,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: s.medicationLabel,
                  hintText: s.medicationHint,
                  alignLabelWithHint: true,
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Prompt(s.allergiesLabel),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final (i, label) in s.allergySuggestions.indexed)
                        _Choice(
                          label: label,
                          selected: _has(_allergies, label, allergyTerms[i]),
                          onTap: () => _toggle(
                            _allergies,
                            label,
                            terms: allergyTerms[i],
                            exclusive: s.allergySuggestions.first,
                            exclusiveTerms: allergyTerms.first,
                          ),
                        ),
                    ],
                  ),
                ],
              ),
              TextFormField(
                controller: _allergies,
                minLines: 1,
                maxLines: 3,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: s.allergiesShort,
                  hintText: s.allergiesHint,
                  alignLabelWithHint: true,
                  prefixIcon: const Icon(Icons.health_and_safety_outlined),
                ),
              ),
              // Asked by the voice agent only when the complaint made it
              // matter; the patient can correct the answer here.
              if (widget.initial.pregnancy.isNotEmpty)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _Prompt(s.pregnancyQuestion),
                    Row(
                      children: [
                        for (final (i, answer) in const [
                          'yes',
                          'no',
                          'unsure',
                        ].indexed) ...[
                          if (i > 0) const SizedBox(width: 12),
                          Expanded(
                            child: _Choice(
                              label: s.pregnancyAnswer(answer),
                              selected: _pregnancy == answer,
                              expand: true,
                              onTap: () => setState(() => _pregnancy = answer),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: 20),
          _Section(
            number: 4,
            icon: Icons.favorite_outline_rounded,
            color: MedoraColors.ochre,
            title: s.healthTitle,
            subtitle: s.healthSubtitle,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Prompt(s.conditionsLabel),
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final (i, label) in s.conditionSuggestions.indexed)
                        _Choice(
                          label: label,
                          selected: _has(_conditions, label, conditionTerms[i]),
                          onTap: () => _toggle(
                            _conditions,
                            label,
                            terms: conditionTerms[i],
                            exclusive: s.conditionSuggestions.first,
                            exclusiveTerms: conditionTerms.first,
                          ),
                        ),
                    ],
                  ),
                ],
              ),
              TextFormField(
                key: const Key('intake-conditions'),
                controller: _conditions,
                minLines: 1,
                maxLines: 3,
                decoration: InputDecoration(
                  labelText: s.conditionsLabel,
                  alignLabelWithHint: true,
                ),
              ),
              TextFormField(
                key: const Key('intake-regular'),
                controller: _regular,
                minLines: 1,
                maxLines: 3,
                decoration: InputDecoration(
                  labelText: s.regularMedicinesLabel,
                  prefixIcon: const Icon(Icons.medication_liquid_outlined),
                ),
              ),
              TextFormField(
                key: const Key('intake-habits'),
                controller: _habits,
                minLines: 1,
                maxLines: 2,
                decoration: InputDecoration(
                  labelText: s.habitsLabel,
                  prefixIcon: const Icon(Icons.smoking_rooms_outlined),
                ),
              ),
              _FieldRow(
                children: [
                  TextFormField(
                    controller: _surgeries,
                    decoration: InputDecoration(labelText: s.surgeriesLabel),
                  ),
                  TextFormField(
                    key: const Key('intake-weight'),
                    controller: _weight,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
                      LengthLimitingTextInputFormatter(5),
                    ],
                    decoration: InputDecoration(
                      labelText: s.weightLabel,
                      prefixIcon: const Icon(Icons.monitor_weight_outlined),
                    ),
                    validator: (v) {
                      final weight = double.tryParse(
                        (v ?? '').trim().replaceAll(',', '.'),
                      );
                      final age = int.tryParse(_age.text.trim());
                      if ((v ?? '').trim().isEmpty) {
                        return age != null && age < 12 ? s.weightLabel : null;
                      }
                      return weight == null || weight <= 0 || weight > 400
                          ? s.weightLabel
                          : null;
                    },
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 28),
          FilledButton(
            onPressed: _submit,
            style: FilledButton.styleFrom(minimumSize: const Size(0, 62)),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(widget.submitLabel),
                const SizedBox(width: 10),
                const Icon(Icons.arrow_forward_rounded),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// An icon for each of [S.symptomSuggestions], in the same order. The
/// wording comes from the kiosk's language and is what goes into the
/// intake, so it stays plain.
const symptomIcons = [
  Icons.thermostat_rounded,
  Icons.air_rounded,
  Icons.ac_unit_rounded,
  Icons.record_voice_over_outlined,
  Icons.psychology_alt_outlined,
  Icons.accessibility_new_rounded,
  Icons.sentiment_dissatisfied_outlined,
  Icons.sick_outlined,
  Icons.water_drop_outlined,
  Icons.favorite_border_rounded,
  Icons.masks_outlined,
  Icons.cyclone_rounded,
  Icons.battery_2_bar_rounded,
  Icons.back_hand_outlined,
  Icons.airline_seat_recline_normal_rounded,
  Icons.wc_rounded,
];

/// Pairs two lists item by item.
Iterable<(A, B)> _zip<A, B>(List<A> a, List<B> b) sync* {
  for (var i = 0; i < a.length && i < b.length; i++) {
    yield (a[i], b[i]);
  }
}

/// A small heading above a group of choices.
class _Prompt extends StatelessWidget {
  const _Prompt(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w700,
          color: MedoraColors.text,
        ),
      ),
    );
  }
}

/// A tappable answer: filled when chosen.
class _Choice extends StatelessWidget {
  const _Choice({
    required this.label,
    required this.selected,
    required this.onTap,
    this.icon,
    this.expand = false,
  });

  final String label;
  final IconData? icon;
  final bool selected;
  final VoidCallback onTap;

  /// Fills the width it is given (for a row of equal tiles).
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final foreground = selected ? Colors.white : MedoraColors.text;
    return Semantics(
      button: true,
      selected: selected,
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 140),
            constraints: const BoxConstraints(minHeight: 52),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              gradient: selected
                  ? MedoraTheme.tint(MedoraColors.primary)
                  : null,
              color: selected ? null : MedoraColors.field,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: selected ? MedoraColors.primary : MedoraColors.border,
              ),
              boxShadow: selected
                  ? const [
                      BoxShadow(
                        color: Color(0x331D4D3B),
                        blurRadius: 12,
                        offset: Offset(0, 5),
                      ),
                    ]
                  : null,
            ),
            child: Row(
              mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  selected ? Icons.check_circle_rounded : icon,
                  size: icon == null && !selected ? 0 : 20,
                  color: selected ? Colors.white : MedoraColors.primary,
                ),
                if (icon != null || selected) const SizedBox(width: 8),
                Flexible(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 15.5,
                      fontWeight: FontWeight.w600,
                      color: foreground,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({
    required this.number,
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.children,
  });

  final int number;
  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.all(26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 50,
                height: 50,
                decoration: BoxDecoration(
                  gradient: MedoraTheme.tint(color),
                  borderRadius: BorderRadius.circular(15),
                  boxShadow: [
                    BoxShadow(
                      color: color.withValues(alpha: 0.3),
                      blurRadius: 14,
                      offset: const Offset(0, 6),
                    ),
                  ],
                ),
                child: Icon(icon, color: Colors.white, size: 26),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      S.of(context).stepOf(number, 4),
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 1.1,
                        color: color,
                      ),
                    ),
                    Text(title, style: text.titleLarge?.copyWith(fontSize: 21)),
                    Text(
                      subtitle,
                      style: text.bodyMedium?.copyWith(fontSize: 14.5),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          for (final child in children) ...[const SizedBox(height: 16), child],
        ],
      ),
    );
  }
}

/// Side by side on wide screens, stacked on narrow ones.
class _FieldRow extends StatelessWidget {
  const _FieldRow({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 520) {
          return Column(
            children: [
              for (final (i, child) in children.indexed) ...[
                if (i > 0) const SizedBox(height: 16),
                child,
              ],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final (i, child) in children.indexed) ...[
              if (i > 0) const SizedBox(width: 16),
              Expanded(child: child),
            ],
          ],
        );
      },
    );
  }
}
