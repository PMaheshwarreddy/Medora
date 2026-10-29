import 'package:flutter/material.dart';

import '../../theme/medora_theme.dart';
import '../hospital_api.dart';
import '../hospital_widgets.dart';

/// The hospital's doctors (`role: doctor`) or staff (`role: staff`): add,
/// edit, switch off, and reset a password.
class PeoplePage extends StatefulWidget {
  const PeoplePage({super.key, required this.api, required this.role});

  final HospitalApi api;
  final String role;

  @override
  State<PeoplePage> createState() => _PeoplePageState();
}

class _PeoplePageState extends State<PeoplePage>
    with HospitalLoader<PeoplePage> {
  List<Map<String, dynamic>> _people = [];
  List<Map<String, dynamic>> _departments = [];

  bool get _doctors => widget.role == 'doctor';

  @override
  Future<void> load() async {
    final people = await widget.api.get(
      '/people',
      query: {'role': widget.role},
    );
    final departments = _doctors
        ? ((await widget.api.get('/departments') as Map)['departments'] as List)
        : const [];
    if (!mounted) return;
    setState(() {
      _people = (people as List).cast<Map<String, dynamic>>();
      _departments = departments.cast<Map<String, dynamic>>();
    });
  }

  Future<void> _edit([Map<String, dynamic>? person]) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _PersonDialog(
        role: widget.role,
        person: person,
        departments: [
          for (final d in _departments)
            if (d['active'] == true || d['id'] == person?['departmentId']) d,
        ],
      ),
    );
    if (result == null) return;
    await run(() async {
      if (person == null) {
        final made =
            await widget.api.send(
                  'POST',
                  '/people',
                  body: {...result, 'role': widget.role},
                )
                as Map<String, dynamic>;
        if (mounted) {
          await showTemporaryPassword(
            context,
            who: (made['person'] as Map)['name'] as String,
            email: (made['person'] as Map)['email'] as String,
            password: made['temporaryPassword'] as String,
          );
        }
      } else {
        await widget.api.send('PATCH', '/people/${person['id']}', body: result);
      }
    });
  }

  Future<void> _toggle(Map<String, dynamic> person) => run(
    () => widget.api.send(
      'PATCH',
      '/people/${person['id']}',
      body: {'active': person['active'] != true},
    ),
  );

  Future<void> _reset(Map<String, dynamic> person) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Reset ${person['name']}\'s password?'),
        content: const Text(
          'They are signed out everywhere and get a temporary password, '
          'which they change when they next sign in.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Reset password'),
          ),
        ],
      ),
    );
    if (sure != true) return;
    await run(() async {
      final body =
          await widget.api.send(
                'POST',
                '/people/${person['id']}/reset-password',
              )
              as Map<String, dynamic>;
      if (mounted) {
        await showTemporaryPassword(
          context,
          who: person['name'] as String,
          email: person['email'] as String,
          password: body['temporaryPassword'] as String,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final title = _doctors ? 'Doctors' : 'Staff';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PageHeading(
          title,
          _doctors
              ? 'The doctors who will use the doctor portal. A registration '
                    'number is needed: it goes on their prescriptions.'
              : 'Nurses and front-desk staff, who will help patients enter '
                    'their details.',
          action: FilledButton.icon(
            key: Key('add-${widget.role}'),
            onPressed: () => _edit(),
            icon: const Icon(Icons.person_add_alt_1_rounded),
            label: Text(_doctors ? 'Add doctor' : 'Add staff'),
          ),
        ),
        ...status(),
        Panel(
          title: '${_people.length} ${title.toLowerCase()}',
          child: Rows(
            columns: [
              'Name',
              'Email',
              if (_doctors) ...['Department', 'Registration no.'] else 'Role',
              'Last sign-in',
              'Status',
              '',
            ],
            rows: [
              for (final p in _people)
                [
                  Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        p['name'] as String,
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      if ((p['qualification'] as String? ?? '').isNotEmpty)
                        Text(
                          p['qualification'] as String,
                          style: const TextStyle(
                            fontSize: 12.5,
                            color: MedoraColors.muted,
                          ),
                        ),
                    ],
                  ),
                  Text(p['email'] as String),
                  if (_doctors) ...[
                    Text(
                      (p['department'] as String?)?.isNotEmpty == true
                          ? p['department'] as String
                          : '—',
                    ),
                    Text(p['registrationNumber'] as String? ?? ''),
                  ] else
                    Text(
                      (p['jobTitle'] as String?)?.isNotEmpty == true
                          ? p['jobTitle'] as String
                          : 'Staff',
                    ),
                  Text(when(p['lastLoginAt'])),
                  p['active'] == true
                      ? (p['mustChangePassword'] == true
                            ? const Tag('Not signed in yet', MedoraColors.ochre)
                            : const Tag('Active', MedoraColors.teal))
                      : const Tag('Switched off', MedoraColors.muted),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: 'Edit',
                        onPressed: () => _edit(p),
                        icon: const Icon(Icons.edit_outlined, size: 20),
                      ),
                      IconButton(
                        tooltip: 'Reset password',
                        onPressed: () => _reset(p),
                        icon: const Icon(Icons.key_rounded, size: 20),
                      ),
                      IconButton(
                        tooltip: p['active'] == true
                            ? 'Switch off'
                            : 'Switch on',
                        onPressed: () => _toggle(p),
                        icon: Icon(
                          p['active'] == true
                              ? Icons.block_rounded
                              : Icons.check_circle_outline,
                          size: 20,
                        ),
                      ),
                    ],
                  ),
                ],
            ],
          ),
        ),
      ],
    );
  }
}

class _PersonDialog extends StatefulWidget {
  const _PersonDialog({
    required this.role,
    required this.person,
    required this.departments,
  });

  final String role;
  final Map<String, dynamic>? person;
  final List<Map<String, dynamic>> departments;

  @override
  State<_PersonDialog> createState() => _PersonDialogState();
}

class _PersonDialogState extends State<_PersonDialog> {
  final _form = GlobalKey<FormState>();
  late final _name = TextEditingController(
    text: widget.person?['name'] as String? ?? '',
  );
  late final _email = TextEditingController(
    text: widget.person?['email'] as String? ?? '',
  );
  late final _phone = TextEditingController(
    text: widget.person?['phone'] as String? ?? '',
  );
  late final _registration = TextEditingController(
    text: widget.person?['registrationNumber'] as String? ?? '',
  );
  late final _qualification = TextEditingController(
    text: widget.person?['qualification'] as String? ?? '',
  );
  late final _job = TextEditingController(
    text: widget.person?['jobTitle'] as String? ?? '',
  );
  late String? _department = widget.person?['departmentId'] as String?;

  bool get _doctor => widget.role == 'doctor';

  @override
  void dispose() {
    for (final c in [
      _name,
      _email,
      _phone,
      _registration,
      _qualification,
      _job,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _required(String? v, String what) =>
      (v ?? '').trim().isEmpty ? 'Enter $what' : null;

  void _save() {
    if (!_form.currentState!.validate()) return;
    Navigator.pop(context, {
      'name': _name.text.trim(),
      'email': _email.text.trim(),
      'phone': _phone.text.trim(),
      if (_doctor) ...{
        'departmentId': _department,
        'registrationNumber': _registration.text.trim(),
        'qualification': _qualification.text.trim(),
      } else
        'jobTitle': _job.text.trim(),
    });
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.person != null;
    return AlertDialog(
      title: Text(
        editing
            ? 'Edit ${widget.person!['name']}'
            : (_doctor ? 'Add a doctor' : 'Add staff'),
      ),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _form,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  key: const Key('person-name'),
                  controller: _name,
                  decoration: InputDecoration(
                    labelText: _doctor
                        ? 'Full name (e.g. Dr. Anita Nair)'
                        : 'Full name',
                  ),
                  validator: (v) => _required(v, 'a name'),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  key: const Key('person-email'),
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(
                    labelText: 'Email (their sign-in)',
                  ),
                  validator: (v) =>
                      (v ?? '').contains('@') ? null : 'Enter a valid email',
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _phone,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                    labelText: 'Phone (optional)',
                  ),
                ),
                const SizedBox(height: 12),
                if (_doctor) ...[
                  DropdownButtonFormField<String?>(
                    key: const Key('person-department'),
                    initialValue: _department,
                    decoration: const InputDecoration(labelText: 'Department'),
                    items: [
                      const DropdownMenuItem(
                        value: null,
                        child: Text('No department yet'),
                      ),
                      for (final d in widget.departments)
                        DropdownMenuItem(
                          value: d['id'] as String,
                          child: Text(d['name'] as String),
                        ),
                    ],
                    onChanged: (v) => setState(() => _department = v),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    key: const Key('person-registration'),
                    controller: _registration,
                    decoration: const InputDecoration(
                      labelText: 'Medical registration number',
                    ),
                    validator: (v) => _required(v, 'the registration number'),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _qualification,
                    decoration: const InputDecoration(
                      labelText: 'Qualification (e.g. MBBS, MD)',
                    ),
                  ),
                ] else
                  TextFormField(
                    controller: _job,
                    decoration: const InputDecoration(
                      labelText: 'Job title (e.g. Nurse, Front desk)',
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('person-save'),
          onPressed: _save,
          child: Text(editing ? 'Save' : 'Create account'),
        ),
      ],
    );
  }
}
