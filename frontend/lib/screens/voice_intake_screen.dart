import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';
import '../state/kiosk_context.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import '../voice/voice_controller.dart';
import '../widgets/medora_orb.dart';
import '../widgets/medora_scaffold.dart';
import '../widgets/band_panel.dart';

/// Live conversation with Dr. Medora.
class VoiceIntakeScreen extends ConsumerStatefulWidget {
  const VoiceIntakeScreen({super.key});

  @override
  ConsumerState<VoiceIntakeScreen> createState() => _VoiceIntakeScreenState();
}

class _VoiceIntakeScreenState extends ConsumerState<VoiceIntakeScreen> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    // Providers cannot be modified while the tree is building.
    Future.microtask(() {
      if (mounted) ref.read(voiceControllerProvider.notifier).start();
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _typeInstead() {
    ref.read(intakeProvider.notifier).start(IntakeMode.manual);
    context.go('/kiosk/manual');
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final manual = ref.watch(kioskConfigProvider).manualIntake;
    final voice = ref.watch(voiceControllerProvider);

    ref.listen(voiceControllerProvider, (previous, next) {
      if (next.status == VoiceStatus.complete) context.go('/kiosk/review');
      if (next.lines.length != previous?.lines.length ||
          (next.lines.isNotEmpty &&
              next.lines.last.text != previous?.lines.lastOrNull?.text)) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (_scroll.hasClients) {
            _scroll.jumpTo(_scroll.position.maxScrollExtent);
          }
        });
      }
    });

    final stopped =
        voice.status == VoiceStatus.unavailable ||
        voice.status == VoiceStatus.error;
    final heardSymptoms = ref.watch(
      intakeProvider.select((s) => s.patient.symptoms.trim().isNotEmpty),
    );
    final (orb, headline) = switch (voice.status) {
      VoiceStatus.live when voice.paused => (OrbState.idle, s.paused),
      VoiceStatus.connecting => (OrbState.thinking, s.connectingMedora),
      VoiceStatus.live when voice.takingVitals => (
        OrbState.thinking,
        s.takingVitals,
      ),
      VoiceStatus.live when voice.speaking => (
        OrbState.speaking,
        s.medoraSpeaking,
      ),
      VoiceStatus.live => (OrbState.listening, s.listening),
      VoiceStatus.complete => (OrbState.idle, s.thankYou),
      _ => (OrbState.idle, s.medoraUnavailable),
    };

    return MedoraScaffold(
      step: FlowStep.intake,
      // The conversation runs in the language it started in.
      languageSwitch: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(child: MedoraOrb(size: 180, state: orb)),
          const SizedBox(height: 16),
          Text(
            headline,
            style: text.headlineSmall,
            textAlign: TextAlign.center,
          ),
          if (voice.status == VoiceStatus.live && !voice.takingVitals) ...[
            const SizedBox(height: 4),
            Text(
              voice.paused ? s.pausedDetail : s.speakNaturally,
              style: text.bodyMedium,
              textAlign: TextAlign.center,
            ),
          ],
          const SizedBox(height: 20),
          if (stopped) ...[
            MedoraNotice(
              icon: voice.status == VoiceStatus.error
                  ? Icons.error_outline
                  : Icons.cloud_off,
              message: [
                // The server's reason is in English; in Malayalam the
                // plain statement is clearer than a mixed sentence.
                s.language == AppLanguage.english
                    ? voice.message ?? s.voiceUnavailable
                    : s.voiceUnavailable,
                if (heardSymptoms)
                  s.toldIsSaved
                else if (manual)
                  s.canTypeInstead,
              ].join(' '),
            ),
            const SizedBox(height: 20),
          ],
          if (voice.takingVitals) ...[
            BandPanel(
              onFinished: ref
                  .read(voiceControllerProvider.notifier)
                  .vitalsFinished,
              onSkip: () => ref
                  .read(voiceControllerProvider.notifier)
                  .vitalsFinished(null),
            ),
            const SizedBox(height: 20),
          ],
          if (!stopped) ...[
            _Transcript(lines: voice.lines, controller: _scroll),
            const SizedBox(height: 16),
            _HeardSoFar(patient: ref.watch(intakeProvider).patient),
            const SizedBox(height: 24),
          ],
          Wrap(
            spacing: 16,
            runSpacing: 16,
            alignment: WrapAlignment.center,
            children: [
              // For noise or an interruption: the microphone goes off and
              // Medora waits until the patient is ready again.
              if (voice.status == VoiceStatus.live && !voice.takingVitals)
                voice.paused
                    ? FilledButton.icon(
                        key: const Key('voice-resume'),
                        onPressed: ref
                            .read(voiceControllerProvider.notifier)
                            .resume,
                        icon: const Icon(Icons.play_arrow_rounded),
                        label: Text(s.resume),
                      )
                    : OutlinedButton.icon(
                        key: const Key('voice-pause'),
                        onPressed: ref
                            .read(voiceControllerProvider.notifier)
                            .pause,
                        icon: const Icon(Icons.pause_rounded),
                        label: Text(s.pause),
                      ),
              // The line dropped part way, but what the patient said is
              // kept: they finish on the review screen instead of starting
              // over.
              if (stopped && heardSymptoms)
                FilledButton.icon(
                  onPressed: () => context.go('/kiosk/review'),
                  icon: const Icon(Icons.fact_check_outlined),
                  label: Text(s.continueWithWhatITold),
                ),
              OutlinedButton.icon(
                onPressed: () => context.go('/kiosk'),
                icon: const Icon(Icons.arrow_back),
                label: Text(stopped ? s.back : s.endConversation),
              ),
              if (manual && !(stopped && heardSymptoms))
                stopped
                    ? FilledButton.icon(
                        onPressed: _typeInstead,
                        icon: const Icon(Icons.touch_app),
                        label: Text(s.typeTitle),
                      )
                    : OutlinedButton.icon(
                        onPressed: _typeInstead,
                        icon: const Icon(Icons.touch_app),
                        label: Text(s.typeInstead),
                      ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Transcript extends StatelessWidget {
  const _Transcript({required this.lines, required this.controller});

  final List<TranscriptLine> lines;
  final ScrollController controller;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return MedoraCard(
      padding: const EdgeInsets.all(16),
      child: SizedBox(
        height: 220,
        child: lines.isEmpty
            ? Center(
                child: Text(
                  S.of(context).conversationAppears,
                  style: text.bodyMedium,
                ),
              )
            : ListView.separated(
                controller: controller,
                itemCount: lines.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (context, i) => _Bubble(line: lines[i]),
              ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.line});

  final TranscriptLine line;

  @override
  Widget build(BuildContext context) {
    final mine = line.fromPatient;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: mine
                ? MedoraColors.teal.withValues(alpha: 0.1)
                : MedoraColors.primary.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                mine ? S.of(context).you : S.of(context).drMedora,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: mine ? MedoraColors.teal : MedoraColors.primary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                line.text,
                style: const TextStyle(fontSize: 16, color: MedoraColors.text),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Shows the patient what Medora has understood, as it fills in.
class _HeardSoFar extends StatelessWidget {
  const _HeardSoFar({required this.patient});

  final PatientIntake patient;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final items = <(String, String)>[
      if (patient.name.isNotEmpty) (s.nameLabel, patient.name),
      if (patient.age != null) (s.age, '${patient.age}'),
      if (patient.gender != null)
        (s.gender, s.genderName(patient.gender!.name)),
      if (patient.phone.isNotEmpty) (s.phone, patient.phone),
      if (patient.symptoms.isNotEmpty) (s.symptomsLabel, patient.symptoms),
      if (patient.duration.isNotEmpty) (s.sinceWhen, patient.duration),
      if (patient.medications.isNotEmpty)
        (s.medicationsLabel, patient.medications),
      if (patient.allergies.isNotEmpty) (s.allergiesShort, patient.allergies),
      if (patient.pregnancy.isNotEmpty)
        (s.pregnancyQuestion, s.pregnancyAnswer(patient.pregnancy)),
    ];
    if (items.isEmpty) return const SizedBox.shrink();
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final (label, value) in items)
          Container(
            constraints: const BoxConstraints(maxWidth: 420),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: MedoraColors.surface,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: MedoraColors.border),
            ),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '$label  ',
                    style: const TextStyle(
                      color: MedoraColors.muted,
                      fontSize: 13,
                    ),
                  ),
                  TextSpan(
                    text: value,
                    style: const TextStyle(
                      color: MedoraColors.text,
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
    );
  }
}
