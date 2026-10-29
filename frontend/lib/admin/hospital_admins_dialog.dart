import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart' show ApiException;
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart' show MedoraNotice;
import 'admin_widgets.dart';

/// The company's one task in a hospital's portal: creating its first
/// administrators (who then add their own doctors and staff), and resetting
/// an administrator's password. The portal itself is `lib/hospital/`.
class HospitalAdminsDialog extends StatefulWidget {
  const HospitalAdminsDialog({
    super.key,
    required this.admin,
    required this.client,
  });

  final AdminApi admin;
  final Map<String, dynamic> client;

  @override
  State<HospitalAdminsDialog> createState() => _HospitalAdminsDialogState();
}

class _HospitalAdminsDialogState extends State<HospitalAdminsDialog> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  List<Map<String, dynamic>> _admins = [];
  String? _error;
  bool _busy = false;

  // Shown once, after creating or resetting an account.
  ({String email, String password})? _issued;

  String get _path =>
      '/api/admin/tenants/${widget.client['id']}/hospital-admins';

  @override
  void initState() {
    super.initState();
    _act(() async {});
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _act(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
      final rows = await widget.admin.get(_path) as List;
      _admins = rows.cast<Map<String, dynamic>>();
    } on ApiException catch (e) {
      _error = e.message;
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _create() => _act(() async {
    final body =
        await widget.admin.send(
              'POST',
              _path,
              body: {
                'name': _name.text.trim(),
                'email': _email.text.trim(),
                'password': _password.text,
              },
            )
            as Map<String, dynamic>;
    _issued = (
      email: (body['person'] as Map)['email'] as String,
      password: body['temporaryPassword'] as String,
    );
    _name.clear();
    _email.clear();
    _password.clear();
  });

  Future<void> _reset(Map<String, dynamic> person) => _act(() async {
    final body =
        await widget.admin.send('POST', '$_path/${person['id']}/reset-password')
            as Map<String, dynamic>;
    _issued = (
      email: person['email'] as String,
      password: body['temporaryPassword'] as String,
    );
  });

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final portal = Uri.base.replace(fragment: '/hospital').toString();
    return AlertDialog(
      title: Text('Hospital portal: ${widget.client['name']}'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'The hospital\'s administrators sign in at the hospital portal '
                'and add their own doctors and staff there.',
                style: text.bodyMedium,
              ),
              const SizedBox(height: 8),
              SelectableText(
                portal,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 13.5),
              ),
              const SizedBox(height: 14),
              if (_busy) const LinearProgressIndicator(minHeight: 3),
              if (_error != null)
                MedoraNotice(icon: Icons.error_outline, message: _error!),
              if (_issued case final issued?) ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: MedoraColors.teal.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: MedoraColors.teal.withValues(alpha: 0.4),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Give these to the administrator. The password is shown '
                        'only now; a temporary one is changed at first sign-in.',
                      ),
                      const SizedBox(height: 8),
                      SelectableText('Email: ${issued.email}'),
                      Row(
                        children: [
                          Expanded(
                            child: SelectableText(
                              'Password: ${issued.password}',
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          IconButton(
                            tooltip: 'Copy',
                            onPressed: () => Clipboard.setData(
                              ClipboardData(text: issued.password),
                            ),
                            icon: const Icon(Icons.copy_rounded),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 16),
              Text('Administrators', style: text.titleMedium),
              const SizedBox(height: 6),
              if (_admins.isEmpty)
                Text(
                  'None yet. Add the first one below.',
                  style: text.bodyMedium,
                )
              else
                for (final a in _admins)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.admin_panel_settings_outlined),
                    title: Text(a['name'] as String),
                    subtitle: Text(
                      '${a['email']}  ·  '
                      '${a['mustChangePassword'] == true ? 'not signed in yet' : 'last sign-in ${formatDate(a['lastLoginAt'])}'}',
                    ),
                    trailing: TextButton(
                      onPressed: _busy ? null : () => _reset(a),
                      child: const Text('Reset password'),
                    ),
                  ),
              const Divider(height: 28),
              Text('Add an administrator', style: text.titleMedium),
              const SizedBox(height: 10),
              TextField(
                key: const Key('hospital-admin-name'),
                controller: _name,
                decoration: const InputDecoration(labelText: 'Full name'),
              ),
              const SizedBox(height: 10),
              TextField(
                key: const Key('hospital-admin-email'),
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: 'Email (their sign-in)',
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                key: const Key('hospital-admin-password'),
                controller: _password,
                decoration: const InputDecoration(
                  labelText: 'Password (optional)',
                  helperText:
                      'At least 8 characters. Leave empty for a temporary '
                      'password they change at first sign-in.',
                ),
              ),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerLeft,
                child: FilledButton.icon(
                  key: const Key('hospital-admin-create'),
                  onPressed: _busy ? null : _create,
                  icon: const Icon(Icons.person_add_alt_1_rounded),
                  label: const Text('Create administrator'),
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
