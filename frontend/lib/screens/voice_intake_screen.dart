import 'dart:math' as math;

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

/// Live conversation with Dr. Medora: her orb, her words as a caption, and
/// ticks for what she has noted. The patient's own words are not shown.
class VoiceIntakeScreen extends ConsumerStatefulWidget {
  const VoiceIntakeScreen({super.key});

  @override
  ConsumerState<VoiceIntakeScreen> createState() => _VoiceIntakeScreenState();
}

class _VoiceIntakeScreenState extends ConsumerState<VoiceIntakeScreen> {
  @override
  void initState() {
    super.initState();
    // Providers cannot be modified while the tree is building.
    Future.microtask(() {
      if (mounted) ref.read(voiceControllerProvider.notifier).start();
    });
  }

  void _typeInstead() {
    ref.read(intakeProvider.notifier).start(IntakeMode.manual);
    context.go('/kiosk/manual');
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final manual = ref.watch(kioskConfigProvider).manualIntake;
    final voice = ref.watch(voiceControllerProvider);

    ref.listen(voiceControllerProvider, (previous, next) {
      if (next.status == VoiceStatus.complete) context.go('/kiosk/review');
    });

    final stopped =
        voice.status == VoiceStatus.unavailable ||
        voice.status == VoiceStatus.error;
    final heardSymptoms = ref.watch(
      intakeProvider.select((s) => s.patient.symptoms.trim().isNotEmpty),
    );
    // Only Dr. Medora's words are shown (the user's request of 2026-10-29):
    // what the patient says is heard and saved, never put on the screen.
    final medoraLines = [
      for (final l in voice.lines)
        if (!l.fromPatient) l.text.trim(),
    ].where((t) => t.isNotEmpty).toList();
    // The patient is talking: the last transcript line is theirs.
    final patientTalking =
        voice.status == VoiceStatus.live &&
        !voice.speaking &&
        voice.lines.isNotEmpty &&
        voice.lines.last.fromPatient;
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
      maxWidth: 860,
      // The conversation runs in the language it started in.
      languageSwitch: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Stage(
            orb: orb,
            headline: headline,
            listening: patientTalking || orb == OrbState.listening,
            live: voice.status == VoiceStatus.live && !voice.paused,
            compact: voice.takingVitals,
          ),
          const SizedBox(height: 18),
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
          ] else if (!stopped) ...[
            _Caption(
              lines: medoraLines,
              dimmed: patientTalking || voice.paused,
            ),
            const SizedBox(height: 22),
            if (voice.status == VoiceStatus.live)
              Text(
                voice.paused ? s.pausedDetail : s.speakNaturally,
                textAlign: TextAlign.center,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(fontSize: 15),
              ),
            const SizedBox(height: 22),
          ],
          if (!stopped) ...[
            _Noted(
              patient: ref.watch(intakeProvider).patient,
              vitals: ref.watch(intakeProvider.select((x) => x.vitals.hasAny)),
            ),
            const SizedBox(height: 26),
          ],
          Wrap(
            spacing: 14,
            runSpacing: 14,
            alignment: WrapAlignment.center,
            crossAxisAlignment: WrapCrossAlignment.center,
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
                        style: FilledButton.styleFrom(
                          minimumSize: const Size(180, 58),
                        ),
                        icon: const Icon(Icons.play_arrow_rounded),
                        label: Text(s.resume),
                      )
                    : OutlinedButton.icon(
                        key: const Key('voice-pause'),
                        onPressed: ref
                            .read(voiceControllerProvider.notifier)
                            .pause,
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size(160, 58),
                        ),
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
              TextButton.icon(
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
                    : TextButton.icon(
                        onPressed: _typeInstead,
                        icon: const Icon(Icons.keyboard_alt_outlined),
                        label: Text(s.typeInstead),
                      ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Dr. Medora on her stage: the orb on a soft halo, and what she is doing
/// now, with sound bars while she listens.
class _Stage extends StatelessWidget {
  const _Stage({
    required this.orb,
    required this.headline,
    required this.listening,
    required this.live,
    required this.compact,
  });

  final OrbState orb;
  final String headline;
  final bool listening;
  final bool live;

  /// Smaller while the band panel needs the room.
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final size = compact ? 120.0 : 200.0;
    return Column(
      children: [
        Container(
          width: size + 90,
          height: size + 90,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(
              colors: [
                MedoraColors.primary.withValues(alpha: 0.10),
                MedoraColors.background.withValues(alpha: 0),
              ],
            ),
          ),
          child: MedoraOrb(size: size, state: orb),
        ),
        const SizedBox(height: 6),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (live && listening) ...[
              const _SoundBars(),
              const SizedBox(width: 10),
            ] else if (live) ...[
              Container(
                width: 9,
                height: 9,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  color: MedoraColors.accent,
                ),
              ),
              const SizedBox(width: 10),
            ],
            Text(
              headline.toUpperCase(),
              style: const TextStyle(
                fontSize: 13,
                letterSpacing: 1.6,
                fontWeight: FontWeight.w700,
                color: MedoraColors.muted,
                fontFamilyFallback: MedoraFonts.fallback,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// Five bars that rise and fall while the patient may speak.
class _SoundBars extends StatefulWidget {
  const _SoundBars();

  @override
  State<_SoundBars> createState() => _SoundBarsState();
}

class _SoundBarsState extends State<_SoundBars>
    with SingleTickerProviderStateMixin {
  late final _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _controller,
    builder: (context, _) => Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        for (var i = 0; i < 5; i++)
          Container(
            width: 3.5,
            height:
                5 +
                11 *
                    (0.5 +
                        0.5 *
                            math.sin(
                              2 * math.pi * (_controller.value + i * 0.18),
                            )),
            margin: const EdgeInsets.symmetric(horizontal: 1.5),
            decoration: BoxDecoration(
              color: MedoraColors.accent,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
      ],
    ),
  );
}

/// What Dr. Medora is saying, large, like a caption; her line before it
/// small and faint above. The patient's own words are never shown.
class _Caption extends StatelessWidget {
  const _Caption({required this.lines, required this.dimmed});

  final List<String> lines;

  /// The patient is answering: her question stays, a little quieter.
  final bool dimmed;

  @override
  Widget build(BuildContext context) {
    final current = lines.isEmpty ? '' : lines.last;
    final before = lines.length > 1 ? lines[lines.length - 2] : '';
    return Container(
      constraints: const BoxConstraints(minHeight: 150),
      padding: const EdgeInsets.fromLTRB(32, 26, 32, 28),
      decoration: BoxDecoration(
        color: MedoraColors.surface,
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: MedoraColors.border),
        boxShadow: MedoraTheme.cardShadow,
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (before.isNotEmpty) ...[
            Text(
              before,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 15,
                height: 1.4,
                color: MedoraColors.muted,
                fontFamilyFallback: MedoraFonts.fallback,
              ),
            ),
            const SizedBox(height: 14),
          ],
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 280),
            transitionBuilder: (child, animation) => FadeTransition(
              opacity: animation,
              child: SlideTransition(
                position: Tween(
                  begin: const Offset(0, 0.08),
                  end: Offset.zero,
                ).animate(animation),
                child: child,
              ),
            ),
            child: AnimatedOpacity(
              // A new line each time Dr. Medora starts speaking again.
              key: ValueKey(lines.length),
              opacity: dimmed ? 0.55 : 1,
              duration: const Duration(milliseconds: 250),
              child: Text(
                current.isEmpty ? '…' : current,
                key: const Key('medora-caption'),
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: MedoraFonts.serif,
                  fontFamilyFallback: MedoraFonts.fallback,
                  fontSize: 30,
                  height: 1.35,
                  fontWeight: FontWeight.w500,
                  color: MedoraColors.text,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// What Dr. Medora has noted so far, as ticks: the topics only, never the
/// answers, so nothing the patient said is shown on the screen.
class _Noted extends StatelessWidget {
  const _Noted({required this.patient, required this.vitals});

  final PatientIntake patient;
  final bool vitals;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final topics = <(String, bool)>[
      (s.yourProblem, patient.symptoms.isNotEmpty),
      (s.age, patient.age != null),
      (s.gender, patient.gender != null),
      (s.sinceWhen, patient.duration.isNotEmpty),
      (s.medicationsLabel, patient.medications.isNotEmpty),
      (s.allergiesShort, patient.allergies.isNotEmpty),
      (s.healthTitle, patient.conditions.isNotEmpty),
      (s.yourVitals, vitals),
      (s.nameLabel, patient.name.isNotEmpty),
      (s.phone, patient.phone.isNotEmpty),
    ];
    final done = topics.where((t) => t.$2).length;
    return Column(
      children: [
        Text(
          '${s.notedSoFar.toUpperCase()}  ·  $done/${topics.length}',
          style: const TextStyle(
            fontSize: 12.5,
            letterSpacing: 1.3,
            fontWeight: FontWeight.w700,
            color: MedoraColors.muted,
            fontFamilyFallback: MedoraFonts.fallback,
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          alignment: WrapAlignment.center,
          children: [
            for (final (label, ok) in topics)
              AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 7,
                ),
                decoration: BoxDecoration(
                  color: ok
                      ? MedoraColors.teal.withValues(alpha: 0.12)
                      : MedoraColors.surface,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: ok
                        ? MedoraColors.teal.withValues(alpha: 0.45)
                        : MedoraColors.border,
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      ok
                          ? Icons.check_circle_rounded
                          : Icons.radio_button_unchecked_rounded,
                      size: 16,
                      color: ok ? MedoraColors.teal : MedoraColors.border,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      // A topic, not a question: "Since when", not "Since when?".
                      label.replaceAll(RegExp(r'[?？]\s*$'), ''),
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: ok ? FontWeight.w700 : FontWeight.w500,
                        color: ok ? MedoraColors.text : MedoraColors.muted,
                        fontFamilyFallback: MedoraFonts.fallback,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ],
    );
  }
}
