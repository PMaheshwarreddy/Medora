import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_client.dart';
import '../l10n/strings.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import '../widgets/intake_form.dart';
import '../widgets/medora_scaffold.dart';
import '../widgets/visited_before.dart';

/// `/phone/<code>`: the intake on the patient's own phone, opened from the
/// kiosk's QR code. The code is the only access; nothing is shown about
/// anyone else.
class PhoneIntakePage extends ConsumerStatefulWidget {
  const PhoneIntakePage({super.key, required this.code});

  final String code;

  @override
  ConsumerState<PhoneIntakePage> createState() => _PhoneIntakePageState();
}

class _PhoneIntakePageState extends ConsumerState<PhoneIntakePage> {
  String _hospital = '';
  String? _error;
  bool _loading = true;
  bool _sent = false;
  bool _sending = false;
  String? _sessionId;
  Timer? _follow;

  ApiClient get _api => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  @override
  void dispose() {
    _follow?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final h = await _api.phoneHandoff(widget.code);
      if (!mounted) return;
      final language = AppLanguage.values
          .where((l) => l.code == h.language)
          .firstOrNull;
      if (language != null) ref.read(languageProvider.notifier).set(language);
      ref.read(intakeProvider.notifier).start(IntakeMode.phone);
      setState(() {
        _hospital = h.hospital;
        _loading = false;
        _sent = h.status != 'open';
        _sessionId = h.sessionId;
      });
      if (_sent && _sessionId == null) _startFollowing();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _error = e.message;
          _loading = false;
        });
      }
    }
  }

  /// After sending: waits for the kiosk to save the visit, for the link.
  void _startFollowing() {
    _follow?.cancel();
    _follow = Timer.periodic(const Duration(seconds: 3), (_) async {
      try {
        final h = await _api.phoneHandoff(widget.code);
        if (h.sessionId != null && mounted) {
          _follow?.cancel();
          setState(() => _sessionId = h.sessionId);
        }
      } on ApiException {
        _follow?.cancel();
      }
    });
  }

  Future<void> _submit(PatientIntake patient) async {
    setState(() {
      _sending = true;
      _error = null;
    });
    final merged = patient.copyWith(
      patientId: ref.read(intakeProvider).patient.patientId,
    );
    try {
      await _api.phoneSubmit(
        widget.code,
        merged,
        ref.read(languageProvider).code,
      );
      if (!mounted) return;
      setState(() => _sent = true);
      _startFollowing();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
    if (mounted) setState(() => _sending = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final text = Theme.of(context).textTheme;
    final List<Widget> body;
    if (_loading) {
      body = [const Center(child: CircularProgressIndicator())];
    } else if (_error != null && !_sent && _hospital.isEmpty) {
      body = [MedoraNotice(icon: Icons.error_outline, message: _error!)];
    } else if (_sent) {
      body = [
        MedoraCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Icon(
                Icons.check_circle_rounded,
                color: MedoraColors.teal,
                size: 56,
              ),
              const SizedBox(height: 12),
              Text(s.phoneSentTitle, style: text.headlineSmall),
              const SizedBox(height: 8),
              Text(s.phoneSentBody, style: text.bodyLarge),
              const SizedBox(height: 20),
              if (_sessionId == null)
                const LinearProgressIndicator(minHeight: 3)
              else
                FilledButton.icon(
                  key: const Key('phone-open-report'),
                  onPressed: () => context.go('/r/$_sessionId'),
                  icon: const Icon(Icons.description_outlined),
                  label: Text(s.phoneFollowReport),
                ),
            ],
          ),
        ),
      ];
    } else {
      final patient = ref.watch(intakeProvider.select((x) => x.patient));
      body = [
        Text(s.phoneFillTitle, style: text.headlineSmall),
        if (_hospital.isNotEmpty)
          Text(
            _hospital,
            style: text.titleMedium?.copyWith(color: MedoraColors.muted),
          ),
        const SizedBox(height: 6),
        Text(s.phoneFillSubtitle, style: text.bodyLarge),
        const SizedBox(height: 20),
        if (_error != null) ...[
          MedoraNotice(icon: Icons.error_outline, message: _error!),
          const SizedBox(height: 16),
        ],
        VisitedBefore(
          find: (visit) => _api.phoneFindPatients(widget.code, visit),
        ),
        const SizedBox(height: 20),
        AbsorbPointer(
          absorbing: _sending,
          child: IntakeForm(
            initial: patient,
            submitLabel: _sending ? s.oneMoment : s.phoneSend,
            onSubmit: _submit,
          ),
        ),
      ];
    }
    return MedoraScaffold(
      maxWidth: 720,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: body,
      ),
    );
  }
}
