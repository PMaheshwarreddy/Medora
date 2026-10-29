import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/strings.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import 'medora_scaffold.dart';

/// "Have you visited before?": the patient types the visit number of an
/// earlier visit (printed on that report) and picks themselves by full
/// name and age (the user's choice of 2026-10-29, replacing a phone
/// number and masked names). Nothing else about them is shown here.
class VisitedBefore extends ConsumerStatefulWidget {
  const VisitedBefore({super.key, required this.find});

  /// Looks a visit number up: the kiosk's or the phone page's endpoint.
  final Future<List<({String id, String label, int? age})>> Function(
    String visit,
  )
  find;

  @override
  ConsumerState<VisitedBefore> createState() => _VisitedBeforeState();
}

class _VisitedBeforeState extends ConsumerState<VisitedBefore> {
  final _visit = TextEditingController();
  List<({String id, String label, int? age})>? _found;
  bool _busy = false;
  // The number typed is too short to be a visit number.
  bool _short = false;

  @override
  void dispose() {
    _visit.dispose();
    super.dispose();
  }

  Future<void> _find() async {
    final visit = _visit.text.replaceAll(RegExp(r'[^0-9A-Za-z]'), '');
    if (visit.length < 6) {
      setState(() => _short = true);
      return;
    }
    setState(() {
      _busy = true;
      _short = false;
    });
    final found = await widget.find(visit);
    if (mounted) {
      setState(() {
        _found = found;
        _busy = false;
      });
    }
  }

  void _pick(String? id) {
    final intake = ref.read(intakeProvider.notifier);
    final patient = ref.read(intakeProvider).patient;
    intake.setPatient(
      id == null
          ? patient.copyWith(clearPatient: true)
          : patient.copyWith(patientId: id),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final text = Theme.of(context).textTheme;
    final picked = ref.watch(intakeProvider.select((x) => x.patient.patientId));
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.visitedTitle, style: text.titleLarge),
          const SizedBox(height: 4),
          Text(s.visitedSubtitle, style: text.bodyMedium),
          const SizedBox(height: 14),
          if (picked != null)
            MedoraNotice(
              icon: Icons.check_circle_outline,
              message: s.welcomeBack,
              color: MedoraColors.teal,
            )
          else ...[
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('visited-number'),
                    controller: _visit,
                    textCapitalization: TextCapitalization.characters,
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(
                        RegExp(r'[0-9A-Za-z -]'),
                      ),
                      LengthLimitingTextInputFormatter(12),
                    ],
                    onSubmitted: (_) => _busy ? null : _find(),
                    decoration: InputDecoration(
                      labelText: s.visitNumberLabel,
                      hintText: 'AB12CD',
                      errorText: _short ? s.visitNumberShort : null,
                      prefixIcon: const Icon(
                        Icons.confirmation_number_outlined,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                FilledButton(
                  key: const Key('visited-find'),
                  onPressed: _busy ? null : _find,
                  child: Text(s.findMe),
                ),
              ],
            ),
            if (_found != null) ...[
              const SizedBox(height: 12),
              if (_found!.isEmpty)
                Text(s.noneFound, style: text.bodyMedium)
              else
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (final p in _found!)
                      OutlinedButton.icon(
                        key: Key('visited-${p.id}'),
                        onPressed: () => _pick(p.id),
                        icon: const Icon(Icons.person_outline_rounded),
                        label: Text(
                          '${p.label}${p.age == null ? '' : ', ${p.age}'}',
                        ),
                      ),
                    TextButton(
                      onPressed: () => setState(() => _found = const []),
                      child: Text(s.imNew),
                    ),
                  ],
                ),
            ],
          ],
          if (picked != null)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () => _pick(null),
                child: Text(s.imNew),
              ),
            ),
        ],
      ),
    );
  }
}
