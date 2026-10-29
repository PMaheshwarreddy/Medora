import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../theme/medora_theme.dart';
import '../../widgets/medora_scaffold.dart' show MedoraNotice;
import '../hospital_api.dart';
import '../hospital_widgets.dart';

/// How the hospital presents itself: name, contact details and logo, used
/// in this portal and (with the doctor portal) on its reports.
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.api, required this.onSaved});

  final HospitalApi api;

  /// The hospital's new `name` and `logo`, for the sidebar.
  final ValueChanged<Map<String, dynamic>> onSaved;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage>
    with HospitalLoader<SettingsPage> {
  final _name = TextEditingController();
  final _address = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _note = TextEditingController();
  String _logo = '';
  String _timezone = 'Asia/Kolkata';
  bool _loaded = false;
  bool _saved = false;

  @override
  void dispose() {
    for (final c in [_name, _address, _phone, _email, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Future<void> load() async {
    if (_loaded) return; // keep what is being edited after a save
    final s = await widget.api.get('/settings') as Map<String, dynamic>;
    if (!mounted) return;
    setState(() {
      _name.text = s['displayName'] as String? ?? '';
      _address.text = s['address'] as String? ?? '';
      _phone.text = s['phone'] as String? ?? '';
      _email.text = s['email'] as String? ?? '';
      _note.text = s['letterheadNote'] as String? ?? '';
      _logo = s['logo'] as String? ?? '';
      _timezone = s['timezone'] as String? ?? 'Asia/Kolkata';
      _loaded = true;
    });
  }

  Future<void> _pickLogo() async {
    final picked = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['png', 'jpg', 'jpeg'],
    );
    if (picked.isEmpty) return;
    final file = picked.first;
    final bytes = await file.readAsBytes();
    if (bytes.length > 300 * 1024) {
      setState(() => error = 'The logo must be 300 KB or smaller.');
      return;
    }
    final type = file.name.toLowerCase().endsWith('.png') ? 'png' : 'jpeg';
    setState(() {
      error = null;
      _logo = 'data:image/$type;base64,${base64Encode(bytes)}';
    });
  }

  Future<void> _save() => run(() async {
    setState(() => _saved = false);
    final s =
        await widget.api.send(
              'PUT',
              '/settings',
              body: {
                'displayName': _name.text.trim(),
                'address': _address.text.trim(),
                'phone': _phone.text.trim(),
                'email': _email.text.trim(),
                'letterheadNote': _note.text.trim(),
                'logo': _logo,
                'timezone': _timezone,
              },
            )
            as Map<String, dynamic>;
    widget.onSaved({
      ...widget.api.hospital,
      'name': (s['displayName'] as String?)?.isNotEmpty == true
          ? s['displayName']
          : widget.api.hospital['name'],
      'logo': s['logo'],
    });
    _saved = true;
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeading(
          'Settings',
          'Your hospital\'s name, contact details and logo. They will appear '
              'on the reports doctors sign.',
        ),
        ...status(),
        if (_saved) ...[
          const MedoraNotice(
            icon: Icons.check_circle_outline,
            message: 'Saved.',
            color: MedoraColors.teal,
          ),
          const SizedBox(height: 16),
        ],
        Panel(
          title: 'Hospital details',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                key: const Key('settings-name'),
                controller: _name,
                decoration: const InputDecoration(
                  labelText: 'Hospital name as shown on reports',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _address,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Address',
                  alignLabelWithHint: true,
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _phone,
                      decoration: const InputDecoration(labelText: 'Phone'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      controller: _email,
                      decoration: const InputDecoration(labelText: 'Email'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _note,
                decoration: const InputDecoration(
                  labelText:
                      'Line under the name (e.g. registration or accreditation)',
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _timezone,
                decoration: const InputDecoration(
                  labelText: 'Time zone (for "today")',
                ),
                items: [
                  for (final zone in {
                    'Asia/Kolkata',
                    'Asia/Dubai',
                    'Asia/Singapore',
                    'Europe/London',
                    'UTC',
                    _timezone,
                  })
                    DropdownMenuItem(value: zone, child: Text(zone)),
                ],
                onChanged: (v) => setState(() => _timezone = v ?? _timezone),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        Panel(
          title: 'Logo',
          subtitle: 'A PNG or JPEG, at most 300 KB.',
          child: Row(
            children: [
              Container(
                width: 88,
                height: 88,
                decoration: BoxDecoration(
                  color: MedoraColors.field,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: MedoraColors.border),
                ),
                clipBehavior: Clip.antiAlias,
                child: _logo.startsWith('data:image')
                    ? Image.memory(
                        base64Decode(_logo.split(',').last),
                        fit: BoxFit.cover,
                      )
                    : const Icon(
                        Icons.local_hospital_outlined,
                        color: MedoraColors.muted,
                        size: 36,
                      ),
              ),
              const SizedBox(width: 18),
              OutlinedButton.icon(
                onPressed: _pickLogo,
                icon: const Icon(Icons.upload_rounded),
                label: Text(_logo.isEmpty ? 'Choose logo' : 'Change logo'),
              ),
              if (_logo.isNotEmpty) ...[
                const SizedBox(width: 10),
                TextButton(
                  onPressed: () => setState(() => _logo = ''),
                  child: const Text('Remove'),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 20),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            key: const Key('settings-save'),
            onPressed: busy ? null : _save,
            icon: const Icon(Icons.save_outlined),
            label: const Text('Save settings'),
          ),
        ),
      ],
    );
  }
}
