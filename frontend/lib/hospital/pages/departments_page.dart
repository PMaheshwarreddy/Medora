import 'package:flutter/material.dart';

import '../../theme/medora_theme.dart';
import '../hospital_api.dart';
import '../hospital_widgets.dart';

/// The hospital's departments. Each can be linked to the department a
/// Medora report names, so those patients reach it.
class DepartmentsPage extends StatefulWidget {
  const DepartmentsPage({super.key, required this.api});

  final HospitalApi api;

  @override
  State<DepartmentsPage> createState() => _DepartmentsPageState();
}

class _DepartmentsPageState extends State<DepartmentsPage>
    with HospitalLoader<DepartmentsPage> {
  List<Map<String, dynamic>> _departments = [];
  List<String> _reportDepartments = [];

  @override
  Future<void> load() async {
    final body = await widget.api.get('/departments') as Map<String, dynamic>;
    if (!mounted) return;
    setState(() {
      _departments = (body['departments'] as List).cast<Map<String, dynamic>>();
      _reportDepartments = (body['reportDepartments'] as List).cast<String>();
    });
  }

  Future<void> _edit([Map<String, dynamic>? department]) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _DepartmentDialog(
        department: department,
        reportDepartments: _reportDepartments,
      ),
    );
    if (result == null) return;
    await run(
      () => department == null
          ? widget.api.send('POST', '/departments', body: result)
          : widget.api.send(
              'PATCH',
              '/departments/${department['id']}',
              body: result,
            ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PageHeading(
          'Departments',
          'Doctors belong to a department, and each department will get its '
              'own patient queue in the doctor portal.',
          action: FilledButton.icon(
            key: const Key('add-department'),
            onPressed: () => _edit(),
            icon: const Icon(Icons.add_rounded),
            label: const Text('Add department'),
          ),
        ),
        ...status(),
        Panel(
          title: '${_departments.length} departments',
          child: Rows(
            columns: const [
              'Name',
              'Takes Medora reports for',
              'Doctors',
              'Status',
              '',
            ],
            rows: [
              for (final d in _departments)
                [
                  Text(
                    d['name'] as String,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  Text(
                    (d['reportDepartment'] as String?)?.isNotEmpty == true
                        ? d['reportDepartment'] as String
                        : '—',
                  ),
                  Text('${d['doctors']}'),
                  d['active'] == true
                      ? const Tag('Active', MedoraColors.teal)
                      : const Tag('Switched off', MedoraColors.muted),
                  IconButton(
                    tooltip: 'Edit',
                    onPressed: () => _edit(d),
                    icon: const Icon(Icons.edit_outlined, size: 20),
                  ),
                ],
            ],
          ),
        ),
      ],
    );
  }
}

class _DepartmentDialog extends StatefulWidget {
  const _DepartmentDialog({
    required this.department,
    required this.reportDepartments,
  });

  final Map<String, dynamic>? department;
  final List<String> reportDepartments;

  @override
  State<_DepartmentDialog> createState() => _DepartmentDialogState();
}

class _DepartmentDialogState extends State<_DepartmentDialog> {
  late final _name = TextEditingController(
    text: widget.department?['name'] as String? ?? '',
  );
  late String _report = widget.department?['reportDepartment'] as String? ?? '';
  late bool _active = widget.department?['active'] as bool? ?? true;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(
        widget.department == null ? 'Add a department' : 'Edit department',
      ),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const Key('department-name'),
              controller: _name,
              decoration: const InputDecoration(
                labelText: 'Name (e.g. Cardiology, General OPD)',
              ),
              onChanged: (value) {
                // Suggest the matching report department while typing.
                final match = widget.reportDepartments.where(
                  (r) => r.toLowerCase() == value.trim().toLowerCase(),
                );
                if (match.isNotEmpty && _report.isEmpty) {
                  setState(() => _report = match.first);
                }
              },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _report,
              decoration: const InputDecoration(
                labelText: 'Takes Medora reports for',
              ),
              items: [
                const DropdownMenuItem(value: '', child: Text('None')),
                for (final r in widget.reportDepartments)
                  DropdownMenuItem(value: r, child: Text(r)),
              ],
              onChanged: (v) => setState(() => _report = v ?? ''),
            ),
            if (widget.department != null)
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Active'),
                value: _active,
                onChanged: (v) => setState(() => _active = v),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('department-save'),
          onPressed: () {
            if (_name.text.trim().isEmpty) return;
            Navigator.pop(context, {
              'name': _name.text.trim(),
              'reportDepartment': _report,
              'active': _active,
            });
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
