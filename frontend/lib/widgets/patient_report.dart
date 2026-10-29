import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../models/intake.dart';
import '../theme/medora_theme.dart';
import 'medora_scaffold.dart';

/// The patient's report, in ONE language: the visit's (the user's rule of
/// 2026-10-28). The pieces the kiosk's report screen and the patient's own
/// page (the doctor's signed report) both show. Wrap them in
/// [ReportLanguage] with the report's language.

/// The language a report is shown in, for the widgets below it.
class ReportLanguage extends InheritedWidget {
  const ReportLanguage({super.key, required this.code, required super.child});

  /// en, ml...: the report's `language`.
  final String code;

  static String codeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<ReportLanguage>()?.code ??
      S.of(context).language.code;

  /// The kiosk strings in the report's language.
  static S stringsOf(BuildContext context) => stringsFor(codeOf(context));

  @override
  bool updateShouldNotify(ReportLanguage old) => old.code != code;
}

/// A patient-report text in the report's language.
class BiText extends StatelessWidget {
  const BiText(this.text, {super.key, this.style, this.color});

  final Bi text;
  final TextStyle? style;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final base =
        style ??
        Theme.of(
          context,
        ).textTheme.bodyLarge?.copyWith(fontSize: 16, height: 1.45);
    return Text(
      text.of(ReportLanguage.codeOf(context)),
      style: base?.copyWith(color: color),
    );
  }
}

/// A section title.
class BiTitle extends StatelessWidget {
  const BiTitle(this.title, {super.key});

  final String title;

  @override
  Widget build(BuildContext context) =>
      Text(title, style: Theme.of(context).textTheme.titleLarge);
}

/// A small label above a value.
class BiLabel extends StatelessWidget {
  const BiLabel(this.label, {super.key});

  final String label;

  @override
  Widget build(BuildContext context) => Text(
    label,
    style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontSize: 13),
  );
}

class BiCard extends StatelessWidget {
  const BiCard({
    super.key,
    required this.title,
    this.paragraphs = const [],
    this.bullets = const [],
  });

  final String title;
  final List<Bi> paragraphs;
  final List<Bi> bullets;

  @override
  Widget build(BuildContext context) {
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          BiTitle(title),
          const SizedBox(height: 12),
          for (final p in paragraphs) BiText(p),
          for (final b in bullets)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 9, right: 10),
                    child: CircleAvatar(
                      radius: 3,
                      backgroundColor: MedoraColors.primary,
                    ),
                  ),
                  Expanded(child: BiText(b)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Rows of a label and a value.
class Rows extends StatelessWidget {
  const Rows(this.rows, {super.key});

  final List<(String, Widget)> rows;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (final (i, (label, value)) in rows.indexed) ...[
        if (i > 0) const Divider(height: 22, color: MedoraColors.border),
        BiLabel(label),
        const SizedBox(height: 4),
        value,
      ],
    ],
  );
}

class PatientCard extends StatelessWidget {
  const PatientCard({super.key, required this.view});

  final PatientView view;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    final value = Theme.of(context).textTheme.bodyLarge;
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          BiTitle(r.patientLabel),
          const SizedBox(height: 12),
          Rows([
            (r.nameLabel, Text(view.name, style: value)),
            (
              '${r.age} / ${r.gender}',
              Text(
                '${view.age ?? ''} / ${r.genderName(view.gender)}',
                style: value,
              ),
            ),
            (r.phone, Text(view.phone, style: value)),
          ]),
        ],
      ),
    );
  }
}

class ToldUsCard extends StatelessWidget {
  const ToldUsCard({super.key, required this.view});

  final PatientView view;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          BiTitle(r.toldUs),
          const SizedBox(height: 12),
          Rows([
            if (view.symptoms case final x?) (r.symptomsLabel, BiText(x)),
            if (view.duration case final x?) (r.sinceWhen, BiText(x)),
            if (view.medicationsTaken case final x?)
              (r.medicinesTaken, BiText(x)),
            if (view.allergies case final x?) (r.allergiesShort, BiText(x)),
          ]),
        ],
      ),
    );
  }
}

/// Each measured vital with its normal range and a verdict worked out in
/// code on the server.
class VitalsCard extends StatelessWidget {
  const VitalsCard({super.key, required this.view});

  final PatientView view;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    final code = ReportLanguage.codeOf(context);
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          BiTitle(r.yourVitals),
          const SizedBox(height: 4),
          Text(
            r.measuredByBand,
            style: text.bodyMedium?.copyWith(fontSize: 13),
          ),
          for (final v in view.vitals) ...[
            const Divider(height: 24, color: MedoraColors.border),
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(r.vitalLabel(v.name), style: text.titleMedium),
                      if (v.normal.isNotEmpty)
                        Text(
                          r.normalRange(v.normal),
                          style: text.bodyMedium?.copyWith(fontSize: 13),
                        ),
                    ],
                  ),
                ),
                Text(
                  v.value,
                  style: const TextStyle(
                    fontSize: 20,
                    fontFamily: MedoraFonts.serif,
                    fontWeight: FontWeight.w600,
                    color: MedoraColors.text,
                  ),
                ),
                const SizedBox(width: 14),
                StatusChip(status: v.status),
              ],
            ),
            if (v.note != null && v.status != 'normal')
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: BiText(
                  v.note!,
                  style: text.bodyMedium?.copyWith(fontSize: 14),
                  color: MedoraColors.warning,
                ),
              ),
          ],
          for (final flag in view.vitalFlags) ...[
            const SizedBox(height: 10),
            MedoraNotice(
              icon: Icons.warning_amber_rounded,
              message: flag.of(code),
            ),
          ],
        ],
      ),
    );
  }
}

class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (status) {
      'normal' => (MedoraColors.teal, Icons.check_circle_rounded),
      'low' => (MedoraColors.warning, Icons.arrow_downward_rounded),
      'high' => (MedoraColors.warning, Icons.arrow_upward_rounded),
      _ => (MedoraColors.muted, Icons.remove_rounded),
    };
    final style = TextStyle(
      color: color,
      fontWeight: FontWeight.w700,
      fontSize: 13,
    );
    return Container(
      constraints: const BoxConstraints(minWidth: 96),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 4),
          Text(
            ReportLanguage.stringsOf(context).vitalStatus(status),
            style: style,
          ),
        ],
      ),
    );
  }
}

/// Medicines with their form, strength and how to take them, for the
/// doctor to confirm.
class MedicinesCard extends StatelessWidget {
  const MedicinesCard({
    super.key,
    required this.medicines,
    this.prescribed = false,
  });

  final List<ViewMedicine> medicines;

  /// The doctor's prescription (signed report), not Medora's suggestions.
  final bool prescribed;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          BiTitle(prescribed ? r.prescribedLabel : r.medicinesForDoctor),
          if (!prescribed) ...[
            const SizedBox(height: 10),
            MedoraNotice(
              icon: Icons.medical_services_outlined,
              message: r.medicinesDoctorOnly,
            ),
          ],
          for (final m in medicines) ...[
            const Divider(height: 28, color: MedoraColors.border),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  [m.name, if (m.strength.isNotEmpty) m.strength].join(' '),
                  style: text.titleMedium?.copyWith(fontSize: 18),
                ),
                if (m.form.isNotEmpty)
                  Tag(r.formName(m.form), MedoraColors.primary),
                if (m.prescription) Tag(r.prescription, MedoraColors.violet),
              ],
            ),
            if (m.doctorOnly && !prescribed) ...[
              const SizedBox(height: 8),
              Text(
                r.doctorGives,
                style: text.bodyMedium?.copyWith(
                  color: MedoraColors.danger,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            if (m.howToTake case final how?) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: MedoraColors.field,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    BiLabel(r.howToTake),
                    const SizedBox(height: 4),
                    BiText(
                      how,
                      style: const TextStyle(
                        fontSize: 15.5,
                        fontWeight: FontWeight.w700,
                        color: MedoraColors.text,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (m.purpose case final purpose?) ...[
              const SizedBox(height: 10),
              BiLabel(r.whatFor),
              const SizedBox(height: 2),
              BiText(purpose, style: text.bodyLarge?.copyWith(fontSize: 15)),
            ],
            if (m.caution case final caution?) ...[
              const SizedBox(height: 10),
              BiLabel(r.cautionLabel),
              const SizedBox(height: 2),
              BiText(
                caution,
                style: text.bodyLarge?.copyWith(fontSize: 15),
                color: MedoraColors.warning,
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class Tag extends StatelessWidget {
  const Tag(this.label, this.color, {super.key});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Text(
      label,
      style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700),
    ),
  );
}

/// Possible conditions in plain words, with one sentence about each; never
/// a percentage on the patient's report.
class ConditionsCard extends StatelessWidget {
  const ConditionsCard({super.key, required this.conditions});

  final List<ViewCondition> conditions;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          BiTitle(r.possibleConditions),
          const SizedBox(height: 4),
          Text(r.notADiagnosis, style: text.bodyMedium?.copyWith(fontSize: 14)),
          for (final c in conditions) ...[
            const Divider(height: 26, color: MedoraColors.border),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: BiText(c.name, style: text.titleMedium)),
                const SizedBox(width: 10),
                LikelihoodChip(c.likelihood),
              ],
            ),
            if (c.about case final about?) ...[
              const SizedBox(height: 6),
              BiText(
                about,
                style: text.bodyLarge?.copyWith(fontSize: 15, height: 1.4),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class LikelihoodChip extends StatelessWidget {
  const LikelihoodChip(this.likelihood, {super.key});

  final String likelihood;

  @override
  Widget build(BuildContext context) {
    final color = switch (likelihood) {
      'high' => MedoraColors.warning,
      'medium' => MedoraColors.primary,
      _ => MedoraColors.muted,
    };
    final style = TextStyle(
      color: color,
      fontSize: 13,
      fontWeight: FontWeight.w600,
    );
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Text(
        ReportLanguage.stringsOf(context).likelihood(likelihood),
        style: style,
      ),
    );
  }
}
