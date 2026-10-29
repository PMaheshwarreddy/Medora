import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';

/// The API as seen by a signed-in back-office user.
class AdminApi {
  AdminApi(this._api, this._key, this.user);

  final ApiClient _api;

  /// The session token.
  final String _key;

  /// Who is signed in: `id`, `name`, `email`.
  final Map<String, dynamic> user;

  String get token => _key;

  /// Where the API is served; shown to staff when handing a client its links.
  String get apiBase => _api.base;

  /// A client that acts as [tenantId], for previewing that client's kiosk.
  ApiClient previewing(String tenantId) => _api.previewing(_key, tenantId);

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _api.adminGet(_key, path, query: query);

  Future<dynamic> send(
    String method,
    String path, {
    Object? body,
    Duration timeout = const Duration(seconds: 30),
  }) => _api.adminSend(_key, method, path, body: body, timeout: timeout);

  Future<dynamic> upload(
    String path, {
    required String filename,
    required Stream<List<int>> bytes,
    required int length,
  }) => _api.adminUpload(
    _key,
    path,
    filename: filename,
    bytes: bytes,
    length: length,
  );
}

/// Shared loading and error handling for a back-office tab.
mixin Loader<T extends StatefulWidget> on State<T> {
  bool busy = false;
  String? error;

  /// Fetches everything the tab shows.
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

  /// Progress bar and error banner to put at the top of the tab.
  List<Widget> statusWidgets() => [
    if (busy) const LinearProgressIndicator(minHeight: 3),
    if (error != null) ...[
      const SizedBox(height: 12),
      MedoraNotice(icon: Icons.error_outline, message: error!),
    ],
    const SizedBox(height: 16),
  ];
}

String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  if (bytes < 1024 * 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
  return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
}

String formatCount(num n) {
  final digits = n.toInt().toString();
  final out = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) out.write(',');
    out.write(digits[i]);
  }
  return out.toString();
}

/// `2026-10-12 14:05` in the viewer's time zone; a dash for null.
String formatDate(Object? iso) {
  if (iso is! String) return '–';
  final d = DateTime.parse(iso).toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)} '
      '${two(d.hour)}:${two(d.minute)}';
}

class StatTile extends StatelessWidget {
  const StatTile(
    this.label,
    this.value, {
    super.key,
    this.detail,
    this.color = MedoraColors.text,
  });

  final String label;
  final String value;
  final String? detail;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: text.bodyMedium),
          const SizedBox(height: 8),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                color: color,
              ),
            ),
          ),
          if (detail != null) ...[
            const SizedBox(height: 4),
            Text(
              detail!,
              style: text.bodyMedium?.copyWith(fontSize: 13),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ],
      ),
    );
  }
}

/// Lays tiles out in as many equal columns as fit.
class TileGrid extends StatelessWidget {
  const TileGrid({super.key, required this.children, this.minTileWidth = 200});

  final List<Widget> children;
  final double minTileWidth;

  @override
  Widget build(BuildContext context) {
    if (children.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 16.0;
        final columns = (constraints.maxWidth / minTileWidth).floor().clamp(
          1,
          children.length,
        );
        final width = (constraints.maxWidth - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final c in children) SizedBox(width: width, child: c),
          ],
        );
      },
    );
  }
}

class Section extends StatelessWidget {
  const Section({
    super.key,
    required this.title,
    required this.child,
    this.subtitle,
    this.actions = const [],
  });

  final String title;
  final String? subtitle;
  final Widget child;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 16,
            runSpacing: 12,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 640),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: text.titleLarge),
                    if (subtitle != null) ...[
                      const SizedBox(height: 4),
                      Text(subtitle!, style: text.bodyMedium),
                    ],
                  ],
                ),
              ),
              if (actions.isNotEmpty)
                Wrap(spacing: 12, runSpacing: 12, children: actions),
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}

/// Wide content scrolls sideways inside the card instead of the page.
class AdminTable extends StatelessWidget {
  const AdminTable({
    super.key,
    required this.columns,
    required this.rows,
    this.onTap,
  });

  final List<String> columns;
  final List<List<Widget>> rows;

  /// Called with the row index when a row is tapped.
  final ValueChanged<int>? onTap;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: ConstrainedBox(
          constraints: BoxConstraints(minWidth: constraints.maxWidth),
          child: DataTable(
            showCheckboxColumn: false,
            headingRowHeight: 44,
            headingRowColor: const WidgetStatePropertyAll(AdminColors.canvas),
            headingTextStyle: const TextStyle(
              fontFamily: MedoraFonts.sans,
              fontSize: 13,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.3,
              color: MedoraColors.muted,
            ),
            dataTextStyle: const TextStyle(
              fontFamily: MedoraFonts.sans,
              fontSize: 14.5,
              color: MedoraColors.text,
            ),
            dividerThickness: 0.6,
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

class Pill extends StatelessWidget {
  const Pill(this.label, this.color, {super.key});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 13,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class EmptyNote extends StatelessWidget {
  const EmptyNote(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 20),
      child: Center(
        child: Text(message, style: Theme.of(context).textTheme.bodyMedium),
      ),
    );
  }
}

/// Text cell that shortens long content and shows all of it on hover.
class Clipped extends StatelessWidget {
  const Clipped(this.text, {super.key, this.width = 280});

  final String text;
  final double width;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(maxWidth: width),
      child: Tooltip(
        message: text,
        child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis),
      ),
    );
  }
}

/// A picker for "all clients" or one of them.
class ClientFilter extends StatelessWidget {
  const ClientFilter({
    super.key,
    required this.clients,
    required this.value,
    required this.onChanged,
  });

  final List<dynamic> clients;
  final String? value;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButton<String?>(
      value: value,
      onChanged: onChanged,
      items: [
        const DropdownMenuItem(value: null, child: Text('All clients')),
        for (final c in clients)
          DropdownMenuItem(
            value: c['id'] as String,
            child: Text(c['name'] as String),
          ),
      ],
    );
  }
}

/// Asks for one line of text. Returns null when cancelled.
Future<String?> askText(
  BuildContext context, {
  required String title,
  required String label,
  required String confirm,
  String? hint,
}) {
  final controller = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: SizedBox(
        width: 460,
        child: TextField(
          controller: controller,
          autofocus: true,
          minLines: 2,
          maxLines: 5,
          decoration: InputDecoration(labelText: label, hintText: hint),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        TextButton(
          onPressed: () {
            final text = controller.text.trim();
            if (text.isNotEmpty) Navigator.pop(context, text);
          },
          child: Text(confirm),
        ),
      ],
    ),
  );
}

/// Back-office palette on top of the kiosk's clinical colours.
abstract final class AdminColors {
  static const canvas = MedoraColors.background;
  static const sidebar = MedoraColors.primaryDark;
  static const sidebarText = Color(0xFFB7C6BD);
  static const sidebarActive = Color(0x29FFFFFF);
}

/// A square holding an icon: soft by default, [solid] for a headline figure.
class IconBadge extends StatelessWidget {
  const IconBadge(
    this.icon,
    this.color, {
    super.key,
    this.size = 40,
    this.solid = false,
  });

  final IconData icon;
  final Color color;
  final double size;
  final bool solid;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: solid ? null : color.withValues(alpha: 0.12),
        gradient: solid ? MedoraTheme.tint(color) : null,
        borderRadius: BorderRadius.circular(size * 0.3),
        boxShadow: solid
            ? [
                BoxShadow(
                  color: color.withValues(alpha: 0.32),
                  blurRadius: 14,
                  offset: const Offset(0, 6),
                ),
              ]
            : null,
      ),
      child: Icon(icon, color: solid ? Colors.white : color, size: size * 0.52),
    );
  }
}

/// One headline figure on the dashboard.
class KpiCard extends StatelessWidget {
  const KpiCard({
    super.key,
    required this.icon,
    required this.color,
    required this.label,
    required this.value,
    this.detail,
  });

  final IconData icon;
  final Color color;
  final String label;
  final String value;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          IconBadge(icon, color, size: 46, solid: true),
          const SizedBox(height: 16),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              style: const TextStyle(
                fontSize: 32,
                height: 1.1,
                fontFamily: MedoraFonts.serif,
                fontWeight: FontWeight.w600,
                letterSpacing: -0.8,
                color: MedoraColors.text,
              ),
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label,
            style: text.titleMedium?.copyWith(fontSize: 14.5),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          if (detail != null)
            Text(
              detail!,
              style: text.bodyMedium?.copyWith(fontSize: 13),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
        ],
      ),
    );
  }
}

/// A value staff need to copy and hand to someone: a link or a key.
class CopyField extends StatelessWidget {
  const CopyField({super.key, required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 6),
        Container(
          padding: const EdgeInsets.only(left: 14, right: 4, top: 4, bottom: 4),
          decoration: BoxDecoration(
            color: AdminColors.canvas,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: MedoraColors.border),
          ),
          child: Row(
            children: [
              Expanded(
                child: SelectableText(
                  value,
                  maxLines: 1,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 14),
                ),
              ),
              IconButton(
                tooltip: 'Copy',
                icon: const Icon(Icons.copy, size: 18),
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: value));
                  if (context.mounted) {
                    ScaffoldMessenger.of(
                      context,
                    ).showSnackBar(SnackBar(content: Text('$label copied')));
                  }
                },
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Two children side by side when there is room, stacked when there is not.
class SplitRow extends StatelessWidget {
  const SplitRow({
    super.key,
    required this.left,
    required this.right,
    this.leftFlex = 3,
    this.rightFlex = 2,
  });

  final Widget left;
  final Widget right;
  final int leftFlex;
  final int rightFlex;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 900) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [left, const SizedBox(height: 16), right],
          );
        }
        return IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(flex: leftFlex, child: left),
              const SizedBox(width: 16),
              Expanded(flex: rightFlex, child: right),
            ],
          ),
        );
      },
    );
  }
}

class AdminSessionController extends Notifier<AdminApi?> {
  @override
  AdminApi? build() => null;

  void unlock(AdminApi admin) => state = admin;

  void lock() => state = null;
}

/// The signed-in back office, or null while signed out. Kept outside the
/// screen so that opening the kiosk and coming back does not sign out.
final adminSessionProvider =
    NotifierProvider<AdminSessionController, AdminApi?>(
      AdminSessionController.new,
    );
