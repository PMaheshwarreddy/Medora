import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';
import '../models/intake.dart';
import '../state/kiosk_context.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import '../widgets/intake_form.dart';
import '../widgets/medora_scaffold.dart';

class ManualIntakeScreen extends ConsumerStatefulWidget {
  const ManualIntakeScreen({super.key});

  @override
  ConsumerState<ManualIntakeScreen> createState() => _ManualIntakeScreenState();
}

class _ManualIntakeScreenState extends ConsumerState<ManualIntakeScreen> {
  bool _checking = false;

  /// Vitals only when the complaint calls for them (the server decides;
  /// when it cannot, they are taken).
  Future<void> _submit(PatientIntake patient) async {
    final intake = ref.read(intakeProvider.notifier)..setPatient(patient);
    if (!ref.read(kioskConfigProvider).smartBand) {
      context.go('/kiosk/review');
      return;
    }
    setState(() => _checking = true);
    final check = await ref
        .read(kioskApiProvider)
        .vitalsCheck(patient, ref.read(languageProvider).code);
    if (!mounted) return;
    setState(() => _checking = false);
    if (check.needed) {
      intake.wantVitals();
      context.go('/kiosk/vitals');
    } else {
      intake.skipVitals(check.reason);
      context.go('/kiosk/review');
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    return MedoraScaffold(
      step: FlowStep.intake,
      maxWidth: 780,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.formTitle, style: text.displaySmall?.copyWith(fontSize: 34)),
          const SizedBox(height: 8),
          Text(
            s.formSubtitle,
            style: text.bodyLarge?.copyWith(color: MedoraColors.muted),
          ),
          const SizedBox(height: 24),
          AbsorbPointer(
            absorbing: _checking,
            child: IntakeForm(
              initial: ref.read(intakeProvider).patient,
              submitLabel: _checking ? s.oneMoment : s.continueLabel,
              onSubmit: _submit,
            ),
          ),
          const SizedBox(height: 12),
          TextButton(
            onPressed: () => context.go('/kiosk'),
            child: Text(s.startOver),
          ),
        ],
      ),
    );
  }
}
