import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart' show ApiException;
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart' show MedoraCard, MedoraNotice;

/// The hospital portal's own building blocks. It shares the Medora look
/// (theme, cards) with the rest of the app, but none of the company back
/// office's code.

/// Loading and error handling for one page.
mixin HospitalLoader<T extends StatefulWidget> on State<T> {
  bool busy = false;
  String? error;

  Future<void> load();

  @override
  void initState() {
    super.initState();
    run(() async {});
  }

  /// Runs [action], then reloads. Failures land in [error].
  Future<void> run(Future<void> Function() action) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } on ApiException catch (e) {
      error = e.message;
    }
    try {
      await load();
    } on ApiException catch (e) {
      error ??= e.message;
    }
    if (mounted) setState(() => busy = false);
  }

  List<Widget> status() => [
    if (busy) const LinearProgressIndicator(minHeight: 3),
    if (error != null) ...[
      const SizedBox(height: 12),
      MedoraNotice(icon: Icons.error_outline, message: error!),
    ],
    const SizedBox(height: 16),
  ];
}

/// A page's title and what it is for.
class PageHeading extends StatelessWidget {
  const PageHeading(this.title, this.subtitle, {super.key, this.action});

  final String title;
  final String subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.end,
        spacing: 16,
        runSpacing: 12,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: text.headlineSmall),
              const SizedBox(height: 4),
              Text(subtitle, style: text.bodyMedium),
            ],
          ),
          ?action,
        ],
      ),
    );
  }
}

class Panel extends StatelessWidget {
  const Panel({
    super.key,
    required this.title,
    required this.child,
    this.subtitle,
  });

  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: text.titleLarge),
          if (subtitle != null) ...[
            const SizedBox(height: 4),
            Text(subtitle!, style: text.bodyMedium),
          ],
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

/// A headline figure.
class Figure extends StatelessWidget {
  const Figure(
    this.label,
    this.value, {
    super.key,
    this.icon,
    this.color = MedoraColors.primary,
  });

  final String label;
  final String value;
  final IconData? icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return MedoraCard(
      padding: const EdgeInsets.all(18),
      child: Row(
        children: [
          if (icon != null) ...[
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: color),
            ),
            const SizedBox(width: 14),
          ],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: Theme.of(context).textTheme.bodyMedium),
                Text(
                  value,
                  style: TextStyle(
                    fontFamily: MedoraFonts.serif,
                    fontSize: 28,
                    fontWeight: FontWeight.w600,
                    color: color,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// As many equal columns as fit.
class Tiles extends StatelessWidget {
  const Tiles({super.key, required this.children, this.minWidth = 220});

  final List<Widget> children;
  final double minWidth;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      const gap = 16.0;
      final columns = (constraints.maxWidth / minWidth).floor().clamp(
        1,
        children.isEmpty ? 1 : children.length,
      );
      final width = (constraints.maxWidth - gap * (columns - 1)) / columns;
      return Wrap(
        spacing: gap,
        runSpacing: gap,
        children: [for (final c in children) SizedBox(width: width, child: c)],
      );
    },
  );
}

class Tag extends StatelessWidget {
  const Tag(this.label, this.color, {super.key});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Text(
      label,
      style: TextStyle(
        color: color,
        fontSize: 12.5,
        fontWeight: FontWeight.w600,
      ),
    ),
  );
}

/// A report's urgency as a coloured tag.
class UrgencyTag extends StatelessWidget {
  const UrgencyTag(this.urgency, {super.key});

  final String? urgency;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (urgency) {
      'emergency' => ('Emergency', MedoraColors.danger),
      'urgent' => ('Urgent', MedoraColors.warning),
      'soon' => ('Soon', MedoraColors.primary),
      'routine' => ('Routine', MedoraColors.teal),
      _ => ('No report', MedoraColors.muted),
    };
    return Tag(label, color);
  }
}

/// A table that scrolls sideways inside its card on a narrow screen.
class Rows extends StatelessWidget {
  const Rows({
    super.key,
    required this.columns,
    required this.rows,
    this.onTap,
  });

  final List<String> columns;
  final List<List<Widget>> rows;
  final ValueChanged<int>? onTap;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 20),
        child: Center(
          child: Text(
            'Nothing here yet.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: ConstrainedBox(
          constraints: BoxConstraints(minWidth: constraints.maxWidth),
          child: DataTable(
            showCheckboxColumn: false,
            headingRowHeight: 42,
            headingRowColor: const WidgetStatePropertyAll(
              MedoraColors.background,
            ),
            headingTextStyle: const TextStyle(
              fontFamily: MedoraFonts.sans,
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: MedoraColors.muted,
            ),
            dataTextStyle: const TextStyle(
              fontFamily: MedoraFonts.sans,
              fontFamilyFallback: MedoraFonts.fallback,
              fontSize: 14.5,
              color: MedoraColors.text,
            ),
            columns: [for (final c in columns) DataColumn(label: Text(c))],
            rows: [
              for (final (i, row) in rows.indexed)
                DataRow(
                  onSelectChanged: onTap == null ? null : (_) => onTap!(i),
                  cells: [for (final cell in row) DataCell(cell)],
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// "19 Oct, 14:05" in the browser's local time.
String when(Object? iso) {
  if (iso is! String) return '—';
  final t = DateTime.tryParse(iso)?.toLocal();
  if (t == null) return '—';
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ]; // fmt: skip
  String two(int n) => n.toString().padLeft(2, '0');
  return '${t.day} ${months[t.month - 1]}, ${two(t.hour)}:${two(t.minute)}';
}

String roleName(Object? role) => switch (role) {
  'hospital_admin' => 'Hospital admin',
  'doctor' => 'Doctor',
  'staff' => 'Staff',
  'company' => 'Medora',
  _ => '$role',
};

/// Shows a temporary password once, with a copy button.
Future<void> showTemporaryPassword(
  BuildContext context, {
  required String who,
  required String email,
  required String password,
}) => showDialog<void>(
  context: context,
  builder: (context) => AlertDialog(
    title: Text('Account ready for $who'),
    content: SizedBox(
      width: 440,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Give these sign-in details to the person. The temporary '
            'password is shown only now; they choose their own when they '
            'first sign in.',
          ),
          const SizedBox(height: 16),
          SelectableText('Email: $email'),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: SelectableText(
                  'Temporary password: $password',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              IconButton(
                tooltip: 'Copy',
                icon: const Icon(Icons.copy_rounded),
                onPressed: () =>
                    Clipboard.setData(ClipboardData(text: password)),
              ),
            ],
          ),
        ],
      ),
    ),
    actions: [
      FilledButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Done'),
      ),
    ],
  ),
);
