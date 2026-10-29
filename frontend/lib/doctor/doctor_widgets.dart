import 'package:flutter/material.dart';

import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart' show MedoraCard;

/// The doctor portal's own building blocks, on the Medora look (paper,
/// pine, one terracotta accent, serif figures).

/// The colour that stands for a report's urgency.
Color urgencyColor(Object? urgency) => switch (urgency) {
  'emergency' => MedoraColors.danger,
  'urgent' => MedoraColors.warning,
  'routine' => MedoraColors.teal,
  _ => MedoraColors.primary,
};

/// "Asha Rao" -> "AR".
String initials(Object? name) {
  final parts = '${name ?? ''}'
      .replaceFirst(RegExp(r'^(dr\.?)\s+', caseSensitive: false), '')
      .split(RegExp(r'\s+'))
      .where((p) => p.isNotEmpty)
      .toList();
  if (parts.isEmpty) return '?';
  final first = parts.first.characters.first;
  final last = parts.length > 1 ? parts.last.characters.first : '';
  return (first + last).toUpperCase();
}

/// "34 · Female" from an age and a gender.
String ageAndSex(Object? age, Object? gender) {
  final g = '${gender ?? ''}'.trim();
  final sex = g.isEmpty ? '' : g[0].toUpperCase() + g.substring(1);
  return [if (age != null) '$age y', if (sex.isNotEmpty) sex].join(' · ');
}

/// "12 min" or "1 h 5 min".
String waited(int minutes) =>
    minutes < 60 ? '$minutes min' : '${minutes ~/ 60} h ${minutes % 60} min';

/// A round badge with someone's initials.
class Initials extends StatelessWidget {
  const Initials(
    this.name, {
    super.key,
    this.size = 44,
    this.color = MedoraColors.primary,
    this.filled = false,
  });

  final Object? name;
  final double size;
  final Color color;

  /// Solid colour with white letters, instead of a soft tint.
  final bool filled;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      shape: BoxShape.circle,
      color: filled ? color : color.withValues(alpha: 0.12),
      border: filled
          ? null
          : Border.all(color: color.withValues(alpha: 0.25), width: 1.2),
    ),
    child: Text(
      initials(name),
      style: TextStyle(
        fontFamily: MedoraFonts.serif,
        fontSize: size * 0.38,
        fontWeight: FontWeight.w600,
        color: filled ? Colors.white : color,
      ),
    ),
  );
}

/// One headline number with a label, for the top of a page.
class StatTile extends StatelessWidget {
  const StatTile({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
    this.color = MedoraColors.primary,
    this.note,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color color;
  final String? note;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label.toUpperCase(),
                  style: text.bodySmall?.copyWith(
                    letterSpacing: 1.1,
                    fontWeight: FontWeight.w700,
                    color: MedoraColors.muted,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  value,
                  style: TextStyle(
                    fontFamily: MedoraFonts.serif,
                    fontSize: 34,
                    height: 1.05,
                    fontWeight: FontWeight.w600,
                    color: color,
                  ),
                ),
                if (note != null) ...[
                  const SizedBox(height: 4),
                  Text(note!, style: text.bodySmall),
                ],
              ],
            ),
          ),
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(icon, color: color),
          ),
        ],
      ),
    );
  }
}

/// A card with an icon, a title and optional words under it.
class Section extends StatelessWidget {
  const Section({
    super.key,
    required this.icon,
    required this.title,
    required this.child,
    this.subtitle,
    this.trailing,
    this.color = MedoraColors.primary,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final Widget child;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.fromLTRB(22, 20, 22, 22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(11),
                ),
                child: Icon(icon, size: 19, color: color),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: text.titleLarge?.copyWith(height: 1.2)),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle!,
                        style: text.bodyMedium?.copyWith(fontSize: 14),
                      ),
                    ],
                  ],
                ),
              ),
              ?trailing,
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}

/// One vital sign as a small tile: the value large, coloured when out of
/// range.
class VitalTile extends StatelessWidget {
  const VitalTile({super.key, required this.vital});

  final Map vital;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final status = '${vital['status'] ?? ''}';
    final off = status == 'low' || status == 'high';
    final color = off ? MedoraColors.accent : MedoraColors.teal;
    final normal = '${vital['normal'] ?? ''}';
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: off
            ? MedoraColors.accent.withValues(alpha: 0.06)
            : MedoraColors.field,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: off
              ? MedoraColors.accent.withValues(alpha: 0.35)
              : MedoraColors.border,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${vital['name']}',
            style: text.bodySmall?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          Text(
            '${vital['value']}',
            style: TextStyle(
              fontFamily: MedoraFonts.serif,
              fontSize: 22,
              fontWeight: FontWeight.w600,
              color: off ? MedoraColors.accent : MedoraColors.text,
            ),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Icon(
                off
                    ? (status == 'high'
                          ? Icons.arrow_upward_rounded
                          : Icons.arrow_downward_rounded)
                    : Icons.check_rounded,
                size: 14,
                color: color,
              ),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  // "High · normal 60–100 bpm", or "In range 95–100%".
                  off
                      ? [
                          status[0].toUpperCase() + status.substring(1),
                          if (normal.isNotEmpty) 'normal $normal',
                        ].join(' · ')
                      : normal.isNotEmpty
                      ? 'In range $normal'
                      : (status.isEmpty ? '' : 'Normal'),
                  maxLines: 2,
                  style: text.bodySmall?.copyWith(color: color),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// English or Malayalam for the patient's signed report. English unless the
/// doctor switches it.
class ReportLanguageToggle extends StatelessWidget {
  const ReportLanguageToggle({
    super.key,
    required this.value,
    required this.onChanged,
  });

  /// 'en' or 'ml'.
  final String value;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) => SegmentedButton<String>(
    key: const Key('report-language'),
    showSelectedIcon: false,
    style: SegmentedButton.styleFrom(
      selectedBackgroundColor: MedoraColors.primary,
      selectedForegroundColor: Colors.white,
      visualDensity: VisualDensity.compact,
    ),
    segments: const [
      ButtonSegment(
        value: 'en',
        label: Text('English', key: Key('report-language-en')),
      ),
      ButtonSegment(
        value: 'ml',
        label: Text(
          'മലയാളം',
          key: Key('report-language-ml'),
          style: TextStyle(fontFamilyFallback: MedoraFonts.fallback),
        ),
      ),
    ],
    selected: {value},
    onSelectionChanged: onChanged == null ? null : (v) => onChanged!(v.first),
  );
}

/// What a language code is called, for the doctor.
String languageName(String code) => switch (code) {
  'ml' => 'Malayalam',
  _ => 'English',
};
