import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../band/band_service.dart';
import '../models/intake.dart';
import '../l10n/strings.dart';
import '../state/kiosk_context.dart';
import '../api/api_client.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import '../widgets/intake_form.dart';
import '../widgets/visited_before.dart';
import '../widgets/medora_scaffold.dart';
import '../widgets/vitals_grid.dart';

/// Shows everything collected so the patient can correct it before analysis.
class ReviewScreen extends ConsumerWidget {
  const ReviewScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final session = ref.watch(intakeProvider);
    final band = ref.watch(kioskConfigProvider).smartBand;
    // The complaint did not call for vitals, and none were taken.
    final skipped = session.vitalsNotNeeded != null && !session.vitals.hasAny;

    return MedoraScaffold(
      step: FlowStep.review,
      maxWidth: 720,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.reviewTitle, style: text.headlineSmall),
          const SizedBox(height: 6),
          Text(
            band && !skipped ? s.reviewSubtitleBand : s.reviewSubtitle,
            style: text.bodyMedium,
          ),
          const SizedBox(height: 20),
          if (!session.patient.isComplete) ...[
            MedoraNotice(icon: Icons.edit_note, message: s.missingDetails),
            const SizedBox(height: 20),
          ],
          if (band && skipped) ...[
            MedoraNotice(
              icon: Icons.check_circle_outline,
              message: session.vitalsNotNeeded!.isEmpty
                  ? s.vitalsNotNeeded
                  : session.vitalsNotNeeded!,
              color: MedoraColors.teal,
            ),
            const SizedBox(height: 20),
          ] else if (band && !session.vitals.hasAny) ...[
            MedoraNotice(icon: Icons.watch_off, message: s.vitalsNotCaptured),
            const SizedBox(height: 20),
          ],
          if (band && !skipped) ...[
            VitalsGrid(
              signs: ref.watch(bandServiceProvider).measures,
              vitals: session.vitals,
              finished: session.vitals.hasAny,
            ),
            const SizedBox(height: 20),
          ],
          // A phone-filled visit was reviewed on the phone: saved at once,
          // so nobody has to touch the kiosk.
          if (session.mode == IntakeMode.phone) ...[
            const _SaveFromPhone(),
          ] else ...[
            VisitedBefore(
              phone: session.patient.phone,
              find: ref.read(kioskApiProvider).findPatients,
            ),
            const SizedBox(height: 20),
            IntakeForm(
              initial: session.patient,
              flagMissing: true,
              submitLabel: s.confirmAndReport,
              onSubmit: (patient) async {
                ref.read(intakeProvider.notifier).setPatient(patient);
                try {
                  final id = await ref
                      .read(kioskApiProvider)
                      .createSession(
                        ref.read(intakeProvider),
                        ref.read(languageProvider).code,
                      );
                  ref.read(intakeProvider.notifier).setSessionId(id);
                } on ApiException catch (e) {
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('${s.notSaved} ${e.message}')),
                  );
                  return;
                }
                if (context.mounted) context.go('/kiosk/report');
              },
            ),
          ],
        ],
      ),
    );
  }
}

/// Saves a visit whose details came from the patient's phone, tells the
/// phone which visit it became, and moves on to the report.
class _SaveFromPhone extends ConsumerStatefulWidget {
  const _SaveFromPhone();

  @override
  ConsumerState<_SaveFromPhone> createState() => _SaveFromPhoneState();
}

class _SaveFromPhoneState extends ConsumerState<_SaveFromPhone> {
  String? _error;

  @override
  void initState() {
    super.initState();
    Future.microtask(_save);
  }

  Future<void> _save() async {
    final api = ref.read(kioskApiProvider);
    final session = ref.read(intakeProvider);
    setState(() => _error = null);
    try {
      final id = await api.createSession(
        session,
        ref.read(languageProvider).code,
      );
      ref.read(intakeProvider.notifier).setSessionId(id);
      if (session.handoffCode != null) {
        try {
          await api.handoffDone(session.handoffCode!, id);
        } on ApiException {
          // The phone just will not show the link; the kiosk carries on.
        }
      }
      if (mounted) context.go('/kiosk/report');
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    if (_error != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MedoraNotice(
            icon: Icons.error_outline,
            message: '${s.notSaved} $_error',
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: _save, child: Text(s.tryAgain)),
        ],
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 40),
      child: Column(
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(s.savingDetails),
        ],
      ),
    );
  }
}
