import 'dart:math';

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';
import 'admin_widgets.dart';
import 'hospital_admins_dialog.dart';

/// Every client (hospital) with its ONE key. The same key goes into the
/// kiosk link and into the `X-Api-Key` header of the client's own system,
/// so a client and its key are managed in one place, with the calls made.
class ClientsTab extends StatefulWidget {
  const ClientsTab({
    super.key,
    required this.admin,
    required this.onPreviewKiosk,
  });

  final AdminApi admin;

  /// Opens the kiosk as the given client.
  final ValueChanged<Map<String, dynamic>> onPreviewKiosk;

  @override
  State<ClientsTab> createState() => _ClientsTabState();
}

class _ClientsTabState extends State<ClientsTab> with Loader {
  List<dynamic> _clients = [];
  List<dynamic> _calls = [];
  // client id -> its live key: calls and last use.
  Map<String, Map<String, dynamic>> _keys = {};
  String? _callsOf;

  @override
  Future<void> load() async {
    final results = await Future.wait([
      widget.admin.get('/api/admin/tenants'),
      widget.admin.get('/api/admin/api-keys'),
      widget.admin.get(
        '/api/admin/api-logs',
        query: {'limit': '100', 'tenant_id': ?_callsOf},
      ),
    ]);
    _clients = results[0] as List;
    _keys = {
      for (final k in (results[1] as List).cast<Map<String, dynamic>>())
        if (k['revoked'] != true) k['tenantId'] as String: k,
    };
    _calls = results[2] as List;
  }

  /// Applies [change] on screen at once and saves it in the background;
  /// if saving fails the switch goes back and the reason is shown.
  Future<void> _patch(String id, Map<String, Object> change) async {
    final client = _clients.cast<Map<String, dynamic>>().firstWhere(
      (c) => c['id'] == id,
    );
    final before = {for (final k in change.keys) k: client[k]};
    setState(() => client.addAll(change));
    try {
      final saved =
          await widget.admin.send(
                'PATCH',
                '/api/admin/tenants/$id',
                body: change,
              )
              as Map<String, dynamic>;
      if (mounted) setState(() => client.addAll(saved));
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => client.addAll(before));
      _say(e.message);
    }
  }

  void _say(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  Future<void> _add() async {
    final body = await showDialog<Map<String, Object>>(
      context: context,
      builder: (context) => const _NewClientDialog(),
    );
    if (body == null) return;
    Map<String, dynamic>? created;
    await run(() async {
      created =
          await widget.admin.send('POST', '/api/admin/tenants', body: body)
              as Map<String, dynamic>;
    });
    if (created != null && mounted) {
      final email = body['adminEmail'] as String? ?? '';
      await _showPackage(
        created!,
        login: email.isEmpty
            ? null
            : (email: email, password: body['adminPassword'] as String),
      );
    }
  }

  Future<void> _newKey(Map<String, dynamic> client) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Issue a new key?'),
        content: Text(
          "The current key of ${client['name']} stops working at once: its "
          'kiosks until they are opened with the new link, and its own '
          'system until it is given the new key.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Issue new key'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    Map<String, dynamic>? updated;
    await run(() async {
      updated =
          await widget.admin.send(
                'POST',
                '/api/admin/tenants/${client['id']}/kiosk-key',
              )
              as Map<String, dynamic>;
    });
    if (updated != null && mounted) await _showPackage(updated!);
  }

  /// What to hand the client. Shown once: the server keeps only a hash of
  /// the key, so neither it nor the link can be shown again.
  Future<void> _showPackage(
    Map<String, dynamic> client, {
    ({String email, String password})? login,
  }) {
    final key = client['kioskKey'] as String;
    // This app's own address, with the kiosk route and the key.
    final link = Uri.base.replace(fragment: '/kiosk?key=$key').toString();
    return showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text('Set up ${client['name']}'),
        content: SizedBox(
          width: 580,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Copy these now. The key is shown only once and cannot be '
                  'recovered later; a new key can be issued instead.',
                ),
                if (login != null) ...[
                  const SizedBox(height: 18),
                  Text(
                    'Hospital portal sign-in',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  CopyField(
                    label: 'Hospital portal',
                    value: Uri.base.replace(fragment: '/hospital').toString(),
                  ),
                  const SizedBox(height: 12),
                  CopyField(label: 'Email', value: login.email),
                  const SizedBox(height: 12),
                  CopyField(label: 'Password', value: login.password),
                  const SizedBox(height: 6),
                  Text(
                    'The hospital administrator signs in with these and adds '
                    'the hospital\'s doctors and staff.',
                    style: Theme.of(
                      context,
                    ).textTheme.bodyMedium?.copyWith(fontSize: 13.5),
                  ),
                  const SizedBox(height: 8),
                  const Divider(),
                ],
                const SizedBox(height: 18),
                CopyField(label: 'Key', value: key),
                const SizedBox(height: 6),
                Text(
                  "This one key identifies the client everywhere: its kiosks "
                  "use it through the link below, and its own software sends "
                  'it in the X-Api-Key header.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontSize: 13.5),
                ),
                const SizedBox(height: 16),
                CopyField(label: 'Kiosk link', value: link),
                const SizedBox(height: 6),
                Text(
                  'Open this link once on each of the client\'s kiosks.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontSize: 13.5),
                ),
                const SizedBox(height: 16),
                CopyField(label: 'API address', value: widget.admin.apiBase),
                const SizedBox(height: 12),
                CopyField(
                  label: 'API documentation',
                  value: '${widget.admin.apiBase}/docs',
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('I have copied them'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final names = {for (final c in _clients) c['id']: c['name'] as String};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        Row(
          children: [
            Expanded(
              child: Text(
                'One client, one key. A kiosk picks up changes the next '
                'time it is reloaded.',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
            const SizedBox(width: 16),
            FilledButton.icon(
              onPressed: busy ? null : _add,
              icon: const Icon(Icons.add),
              key: const Key('add-client'),
              label: const Text('Add client (hospital)'),
            ),
          ],
        ),
        const SizedBox(height: 16),
        for (final c in _clients) ...[
          _ClientCard(
            client: c as Map<String, dynamic>,
            apiKey: _keys[c['id']],
            busy: busy,
            onChange: (change) => _patch(c['id'] as String, change),
            onBlocked: _say,
            onNewKey: () => _newKey(c),
            onPreview: () => widget.onPreviewKiosk(c),
            onHospitalPortal: () => showDialog<void>(
              context: context,
              builder: (_) =>
                  HospitalAdminsDialog(admin: widget.admin, client: c),
            ),
          ),
          const SizedBox(height: 16),
        ],
        Section(
          title: 'Calls made with client keys',
          subtitle:
              "Every request a client's own system sent to the API, "
              'newest first.',
          actions: [
            ClientFilter(
              clients: _clients,
              value: _callsOf,
              onChanged: (id) {
                _callsOf = id;
                run(() async {});
              },
            ),
            IconButton(
              tooltip: 'Refresh',
              onPressed: busy ? null : () => run(() async {}),
              icon: const Icon(Icons.refresh),
            ),
          ],
          child: _calls.isEmpty
              ? const EmptyNote('No calls yet.')
              : AdminTable(
                  columns: const [
                    'Time',
                    'Client',
                    'Request',
                    'Result',
                    'Took',
                  ],
                  rows: [
                    for (final c in _calls)
                      [
                        Text(formatDate(c['at'])),
                        Text(names[c['tenantId']] ?? '–'),
                        Clipped('${c['method']} ${c['path']}', width: 380),
                        (c['status'] as int) < 400
                            ? Pill('${c['status']} OK', MedoraColors.teal)
                            : Pill(
                                '${c['status']} Failed',
                                MedoraColors.danger,
                              ),
                        Text('${c['durationMs']} ms'),
                      ],
                  ],
                ),
        ),
      ],
    );
  }
}

class _NewClientDialog extends StatefulWidget {
  const _NewClientDialog();

  @override
  State<_NewClientDialog> createState() => _NewClientDialogState();
}

class _NewClientDialogState extends State<_NewClientDialog> {
  final _name = TextEditingController();
  final _adminName = TextEditingController();
  final _adminEmail = TextEditingController();
  final _adminPassword = TextEditingController();
  bool _showPassword = false;
  // Why the form cannot be sent yet.
  String? _problem;
  bool _voice = true;
  bool _manual = true;
  bool _band = true;
  // Why the last switch change was refused.
  String? _rule;

  /// One intake mode must stay on.
  void _set({bool? voice, bool? manual}) => setState(() {
    final v = voice ?? _voice;
    final m = manual ?? _manual;
    if (!v && !m) {
      _rule = 'Patients need at least one way in: voice or manual input.';
      return;
    }
    _rule = null;
    _voice = v;
    _manual = m;
  });

  @override
  void dispose() {
    _name.dispose();
    _adminName.dispose();
    _adminEmail.dispose();
    _adminPassword.dispose();
    super.dispose();
  }

  /// A password that is easy to read out: no 0/O or 1/l.
  void _generate() {
    const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789';
    final random = Random.secure();
    setState(() {
      _adminPassword.text = List.generate(
        10,
        (_) => chars[random.nextInt(chars.length)],
      ).join();
      _showPassword = true;
    });
  }

  void _submit() {
    final name = _name.text.trim();
    final adminName = _adminName.text.trim();
    final email = _adminEmail.text.trim();
    final password = _adminPassword.text;
    String? problem;
    if (name.isEmpty) {
      problem = 'Enter the hospital\'s name.';
    } else if (email.isNotEmpty ||
        adminName.isNotEmpty ||
        password.isNotEmpty) {
      if (adminName.isEmpty) {
        problem = "Enter the administrator's name.";
      } else if (!email.contains('@') || !email.contains('.')) {
        problem = 'Enter a valid email for the administrator.';
      } else if (password.length < 8) {
        problem = 'The password needs at least 8 characters.';
      }
    }
    if (problem != null) {
      setState(() => _problem = problem);
      return;
    }
    Navigator.pop<Map<String, Object>>(context, {
      'name': name,
      'voiceIntake': _voice,
      'manualIntake': _manual,
      'smartBand': _band,
      if (email.isNotEmpty) ...{
        'adminName': adminName,
        'adminEmail': email,
        'adminPassword': password,
      },
    });
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AlertDialog(
      title: const Text('Add a client (hospital)'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                key: const Key('client-name'),
                controller: _name,
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Hospital name',
                  hintText: 'For example: City Hospital',
                ),
              ),
              const SizedBox(height: 20),
              Text('Hospital portal sign-in', style: text.titleMedium),
              const SizedBox(height: 4),
              Text(
                "The hospital's administrator signs in to the hospital portal "
                'with this email and password, and adds its doctors and staff.',
                style: text.bodyMedium?.copyWith(fontSize: 13.5),
              ),
              const SizedBox(height: 10),
              TextField(
                key: const Key('client-admin-name'),
                controller: _adminName,
                decoration: const InputDecoration(
                  labelText: "Administrator's full name",
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                key: const Key('client-admin-email'),
                controller: _adminEmail,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email'),
              ),
              const SizedBox(height: 10),
              TextField(
                key: const Key('client-admin-password'),
                controller: _adminPassword,
                obscureText: !_showPassword,
                decoration: InputDecoration(
                  labelText: 'Password (at least 8 characters)',
                  suffixIcon: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: _showPassword ? 'Hide' : 'Show',
                        onPressed: () =>
                            setState(() => _showPassword = !_showPassword),
                        icon: Icon(
                          _showPassword
                              ? Icons.visibility_off_outlined
                              : Icons.visibility_outlined,
                        ),
                      ),
                      TextButton(
                        onPressed: _generate,
                        child: const Text('Generate'),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              Text('Kiosk features', style: text.titleMedium),
              const SizedBox(height: 4),
              _Switch(
                title: 'Voice agent',
                subtitle: 'Patients can talk to Dr. Medora.',
                value: _voice,
                onChanged: (v) => _set(voice: v),
              ),
              _Switch(
                title: 'Manual input',
                subtitle: 'Patients can type their details.',
                value: _manual,
                onChanged: (v) => _set(manual: v),
              ),
              _Switch(
                title: 'Smart band',
                subtitle: 'Vitals are taken from the band.',
                value: _band,
                onChanged: (v) => setState(() => _band = v),
              ),
              if (_rule != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    _rule!,
                    style: const TextStyle(color: MedoraColors.warning),
                  ),
                ),
              if (_problem != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    _problem!,
                    style: const TextStyle(color: MedoraColors.danger),
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('client-create'),
          onPressed: _submit,
          child: const Text('Create'),
        ),
      ],
    );
  }
}

class _ClientCard extends StatelessWidget {
  const _ClientCard({
    required this.client,
    required this.apiKey,
    required this.busy,
    required this.onChange,
    required this.onBlocked,
    required this.onNewKey,
    required this.onPreview,
    required this.onHospitalPortal,
  });

  final Map<String, dynamic> client;

  /// The client's key as the API sees it: calls and last use. Null for the
  /// default client and for clients whose key predates the single key.
  final Map<String, dynamic>? apiKey;
  final bool busy;
  final ValueChanged<Map<String, Object>> onChange;

  /// Explains a change that is not allowed.
  final ValueChanged<String> onBlocked;
  final VoidCallback onNewKey;
  final VoidCallback onPreview;

  /// The hospital's own portal: its administrator logins.
  final VoidCallback onHospitalPortal;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final isDefault = client['isDefault'] as bool;
    final active = client['active'] as bool;
    final voice = client['voiceIntake'] as bool;
    final manual = client['manualIntake'] as bool;
    final hint = client['kioskKeyHint'] as String;
    final calls = apiKey?['callsLast24h'] as int? ?? 0;
    final failed = apiKey?['errorsLast24h'] as int? ?? 0;

    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              IconBadge(
                Icons.apartment_rounded,
                active ? MedoraColors.primary : MedoraColors.muted,
                size: 52,
                solid: true,
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 10,
                      runSpacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(client['name'] as String, style: text.titleLarge),
                        if (isDefault)
                          const Pill('Default', MedoraColors.primary),
                        Pill(
                          active ? 'Active' : 'Switched off',
                          active ? MedoraColors.teal : MedoraColors.muted,
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${formatCount(client['sessions'] as int)} sessions  ·  '
                      'last ${formatDate(client['lastSessionAt'])}',
                      style: text.bodyMedium?.copyWith(fontSize: 14),
                    ),
                  ],
                ),
              ),
              FilledButton.icon(
                onPressed: active ? onPreview : null,
                icon: const Icon(Icons.tablet_mac_outlined, size: 20),
                label: const Text('Open kiosk'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size(0, 46),
                  textStyle: const TextStyle(
                    fontFamily: MedoraFonts.sans,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          // The key: the one thing that identifies this client.
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 10, 12),
            decoration: BoxDecoration(
              color: AdminColors.canvas,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Row(
              children: [
                const Icon(Icons.key_rounded, color: MedoraColors.primary),
                const SizedBox(width: 12),
                Expanded(
                  child: isDefault
                      ? Text(
                          'No key: kiosks opened without a key belong to '
                          'this client.',
                          style: text.bodyMedium?.copyWith(fontSize: 14),
                        )
                      : Wrap(
                          spacing: 18,
                          runSpacing: 4,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              hint,
                              style: const TextStyle(
                                fontFamily: 'monospace',
                                fontSize: 15,
                                fontWeight: FontWeight.w600,
                                color: MedoraColors.text,
                              ),
                            ),
                            Text(
                              apiKey == null
                                  ? 'Issue a new key to use it for API calls too'
                                  : failed == 0
                                  ? '${formatCount(calls)} API calls in 24 h'
                                  : '${formatCount(calls)} API calls in 24 h '
                                        '($failed failed)',
                              style: text.bodyMedium?.copyWith(fontSize: 13.5),
                            ),
                            if (apiKey != null)
                              Text(
                                'last used ${formatDate(apiKey!['lastUsedAt'])}',
                                style: text.bodyMedium?.copyWith(
                                  fontSize: 13.5,
                                ),
                              ),
                          ],
                        ),
                ),
                if (!isDefault)
                  TextButton.icon(
                    onPressed: busy ? null : onNewKey,
                    icon: const Icon(Icons.autorenew, size: 18),
                    label: const Text('New key'),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 10),
          TileGrid(
            minTileWidth: 280,
            children: [
              _Switch(
                title: 'Voice agent',
                subtitle: 'Patients can talk to Dr. Medora.',
                value: voice,
                // One intake mode must stay on.
                // One way in must stay on: say so rather than lock the
                // switch, which looks as if it were off.
                onChanged: (v) => !v && !manual
                    ? onBlocked(
                        'Manual input is off, so the voice agent has to stay '
                        'on. Switch on Manual input first.',
                      )
                    : onChange({'voiceIntake': v}),
              ),
              _Switch(
                title: 'Manual input',
                subtitle: 'Patients can type their details.',
                value: manual,
                onChanged: (v) => !v && !voice
                    ? onBlocked(
                        'The voice agent is off, so manual input has to stay '
                        'on. Switch on the voice agent first.',
                      )
                    : onChange({'manualIntake': v}),
              ),
              _Switch(
                title: 'Smart band',
                subtitle: 'Vitals are taken from the band.',
                value: client['smartBand'] as bool,
                onChanged: (v) => onChange({'smartBand': v}),
              ),
              _Switch(
                title: 'Doctor review',
                subtitle:
                    'A doctor signs each report in the doctor portal before '
                    'the patient gets medicines.',
                value: client['doctorReview'] as bool? ?? true,
                onChanged: (v) => onChange({'doctorReview': v}),
              ),
            ],
          ),
          if (!isDefault)
            Wrap(
              spacing: 8,
              children: [
                TextButton.icon(
                  key: Key('hospital-portal-${client['id']}'),
                  onPressed: onHospitalPortal,
                  icon: const Icon(
                    Icons.admin_panel_settings_outlined,
                    size: 18,
                  ),
                  label: const Text('Hospital portal'),
                ),
                TextButton.icon(
                  onPressed: busy ? null : () => onChange({'active': !active}),
                  icon: Icon(active ? Icons.block : Icons.check, size: 18),
                  label: Text(
                    active ? 'Switch off client' : 'Switch on client',
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

class _Switch extends StatelessWidget {
  const _Switch({
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(title, style: text.titleMedium),
      subtitle: Text(
        subtitle,
        style: text.bodyMedium?.copyWith(fontSize: 13.5),
      ),
      value: value,
      onChanged: onChanged,
    );
  }
}
