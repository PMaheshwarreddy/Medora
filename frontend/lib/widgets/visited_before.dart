import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/strings.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import 'medora_scaffold.dart';

/// "Have you visited before?": the people this hospital knows under the
/// patient's phone number, as masked names, to pick from. Nothing else
/// about them is ever shown here.
class VisitedBefore extends ConsumerStatefulWidget {
  const VisitedBefore({super.key, required this.phone, required this.find});

  final String phone;

  /// Looks a phone number up: the kiosk's or the phone page's endpoint.
  final Future<List<({String id, String label, int? age})>> Function(
    String phone,
  )
  find;

  @override
  ConsumerState<VisitedBefore> createState() => _VisitedBeforeState();
}

class _VisitedBeforeState extends ConsumerState<VisitedBefore> {
  late final _phone = TextEditingController(text: widget.phone);
  List<({String id, String label, int? age})>? _found;
  bool _busy = false;

  @override
  void dispose() {
    _phone.dispose();
    super.dispose();
  }

  Future<void> _find() async {
    setState(() => _busy = true);
    final found = await widget.find(_phone.text.trim());
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
                    key: const Key('visited-phone'),
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    decoration: InputDecoration(
                      labelText: s.phone,
                      prefixIcon: const Icon(Icons.phone_outlined),
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
