import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../api/api_client.dart';
import '../l10n/strings.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';
import '../state/kiosk_context.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';

/// "Use my phone": a QR code the patient (or a nurse helping them) scans
/// to fill the intake on their own phone instead of this shared screen.
/// When the details arrive, the kiosk carries on with vitals and the
/// report by itself.
class PhoneHandoffScreen extends ConsumerStatefulWidget {
  const PhoneHandoffScreen({super.key});

  /// How often the kiosk asks whether the phone has sent the details.
  static const poll = Duration(seconds: 2);

  @override
  ConsumerState<PhoneHandoffScreen> createState() => _PhoneHandoffScreenState();
}

class _PhoneHandoffScreenState extends ConsumerState<PhoneHandoffScreen> {
  String? _code;
  String? _error;
  bool _expired = false;
  bool _received = false;
  Timer? _timer;

  ApiClient get _api => ref.read(kioskApiProvider);

  @override
  void initState() {
    super.initState();
    Future.microtask(_open);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _open() async {
    setState(() {
      _error = null;
      _expired = false;
    });
    try {
      final code = await _api.openHandoff(ref.read(languageProvider).code);
      if (!mounted) return;
      setState(() => _code = code);
      _timer = Timer.periodic(PhoneHandoffScreen.poll, (_) => _check());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _check() async {
    final code = _code;
    if (code == null || _received) return;
    final ({String status, Map<String, dynamic>? intake}) answer;
    try {
      answer = await _api.handoffStatus(code);
    } on ApiException catch (e) {
      if (e.statusCode == 404) {
        _timer?.cancel();
        if (mounted) setState(() => _expired = true);
      }
      return;
    }
    if (answer.intake == null || !mounted) return;
    _timer?.cancel();
    setState(() => _received = true);
    final patient = PatientIntake.fromJson(answer.intake!);
    final language = AppLanguage.values
        .where((l) => l.code == answer.intake!['language'])
        .firstOrNull;
    if (language != null) ref.read(languageProvider.notifier).set(language);
    ref.read(intakeProvider.notifier).fromPhone(code, patient);
    await _onward(patient);
  }

  /// Vitals if the complaint needs them, then the report.
  Future<void> _onward(PatientIntake patient) async {
    if (!ref.read(kioskConfigProvider).smartBand) {
      if (mounted) context.go('/kiosk/review');
      return;
    }
    final check = await _api.vitalsCheck(
      patient,
      ref.read(languageProvider).code,
    );
    if (!mounted) return;
    final intake = ref.read(intakeProvider.notifier);
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
    final s = S.of(context);
    final text = Theme.of(context).textTheme;
    final code = _code;
    return MedoraScaffold(
      step: FlowStep.intake,
      maxWidth: 820,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.phoneScanTitle, style: text.headlineSmall),
          const SizedBox(height: 8),
          Text(s.phoneScanSteps, style: text.bodyLarge),
          const SizedBox(height: 24),
          if (_error != null) ...[
            MedoraNotice(icon: Icons.error_outline, message: _error!),
            const SizedBox(height: 16),
            FilledButton(onPressed: _open, child: Text(s.tryAgain)),
          ] else if (_expired) ...[
            MedoraNotice(
              icon: Icons.timer_off_outlined,
              message: s.phoneExpired,
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: _open, child: Text(s.tryAgain)),
          ] else
            MedoraCard(
              padding: const EdgeInsets.all(28),
              child: Column(
                children: [
                  if (code == null)
                    const SizedBox(
                      height: 280,
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else
                    Container(
                      key: const Key('handoff-qr'),
                      padding: const EdgeInsets.all(14),
                      color: Colors.white,
                      child: QrImageView(
                        data: publicLink('/phone/$code').toString(),
                        size: 280,
                        backgroundColor: Colors.white,
                      ),
                    ),
                  const SizedBox(height: 18),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (_received)
                        const Icon(Icons.check_circle, color: MedoraColors.teal)
                      else
                        const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      const SizedBox(width: 10),
                      Text(
                        _received ? s.phoneReceived : s.phoneWaiting,
                        style: text.titleMedium,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              OutlinedButton.icon(
                onPressed: () => context.go('/kiosk'),
                icon: const Icon(Icons.arrow_back),
                label: Text(s.back),
              ),
              TextButton.icon(
                onPressed: () {
                  ref.read(intakeProvider.notifier).start(IntakeMode.manual);
                  context.go('/kiosk/manual');
                },
                icon: const Icon(Icons.keyboard_alt_outlined),
                label: Text(s.typeHereInstead),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
