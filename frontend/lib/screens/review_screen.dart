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
import '../widgets/band_panel.dart';
import '../widgets/medora_scaffold.dart';
import '../widgets/vitals_grid.dart';

/// Shows everything collected so the patient can correct it before analysis.
/// Vitals are a must: when none were taken (the band failed, or the voice
/// agent moved on without them), the band is offered here and the visit
/// cannot be confirmed until it has measured.
class ReviewScreen extends ConsumerStatefulWidget {
  const ReviewScreen({super.key});

  @override
  ConsumerState<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends ConsumerState<ReviewScreen> {
  /// True while the band panel is up here. It stays up until the
  /// measurement has finished, even though readings arrive one by one.
  late bool _measuring = _vitalsMissing();

  /// A kiosk with a working band whose visit has no vitals yet (and was
  /// not told they are not needed).
  bool _vitalsMissing() {
    final session = ref.read(intakeProvider);
    return ref.read(kioskConfigProvider).smartBand &&
        ref.read(bandServiceProvider).isAvailable &&
        session.vitalsNotNeeded == null &&
        !session.vitals.hasAny;
  }

  Future<void> _confirm(PatientIntake patient, S s) async {
    ref.read(intakeProvider.notifier).setPatient(patient);
    if (_measuring || _vitalsMissing()) {
      setState(() => _measuring = true);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(s.vitalsFirst)));
      return;
    }
    try {
      final id = await ref
          .read(kioskApiProvider)
          .createSession(
            ref.read(intakeProvider),
            ref.read(languageProvider).code,
          );
      ref.read(intakeProvider.notifier).setSessionId(id);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('${s.notSaved} ${e.message}')));
      return;
    }
    if (mounted) context.go('/kiosk/report');
  }

  @override
  Widget build(BuildContext context) {
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
          ] else if (_measuring) ...[
            // Taken here: the measurement on the earlier screen did not
            // happen or did not work.
            MedoraNotice(
              icon: Icons.monitor_heart_outlined,
              message: s.vitalsNeededHere,
            ),
            const SizedBox(height: 16),
            BandPanel(
              key: const Key('review-band'),
              onFinished: (_) {
                if (mounted) setState(() => _measuring = false);
              },
              // Only offered when this kiosk has no usable band at all.
              onSkip: () => setState(() => _measuring = false),
            ),
            const SizedBox(height: 20),
          ] else if (band && !session.vitals.hasAny) ...[
            MedoraNotice(icon: Icons.watch_off, message: s.vitalsNotCaptured),
            const SizedBox(height: 20),
          ],
          if (band && !skipped && !_measuring) ...[
            VitalsGrid(
              signs: ref.watch(bandServiceProvider).measures,
              vitals: session.vitals,
              finished: session.vitals.hasAny,
            ),
            const SizedBox(height: 20),
          ],
          // A phone-filled visit was reviewed on the phone: saved at once,
          // so nobody has to touch the kiosk (after the vitals, if they
          // still had to be taken here).
          if (session.mode == IntakeMode.phone) ...[
            if (!_measuring) const _SaveFromPhone(),
          ] else ...[
            VisitedBefore(find: ref.read(kioskApiProvider).findPatients),
            const SizedBox(height: 20),
            IntakeForm(
              initial: session.patient,
              flagMissing: true,
              submitLabel: s.confirmAndReport,
              onSubmit: (patient) => _confirm(patient, s),
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
