import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';
import '../state/kiosk_context.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';
import '../state/service_status.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_orb.dart';
import '../widgets/medora_scaffold.dart';

class WelcomeScreen extends ConsumerWidget {
  const WelcomeScreen({super.key});

  void _start(BuildContext context, WidgetRef ref, IntakeMode mode) {
    ref.read(intakeProvider.notifier).start(mode);
    context.go(switch (mode) {
      IntakeMode.voice => '/kiosk/voice',
      IntakeMode.phone => '/kiosk/phone',
      IntakeMode.manual => '/kiosk/manual',
    });
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final config = ref.watch(kioskConfigProvider);
    final status = ref.watch(serviceStatusProvider).value;
    // Without internet the form still works (the report runs on the local
    // medical model, see backend offline.py); voice needs the connection.
    final offline = status != null && !status.online;
    final voiceDown = status != null && !status.voice;
    final hour = DateTime.now().hour;
    final greeting = hour < 12
        ? s.goodMorning
        : hour < 17
        ? s.goodAfternoon
        : s.goodEvening;

    final intro = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const MedoraOrb(size: 132),
        const SizedBox(height: 32),
        Text(
          greeting,
          style: text.displaySmall?.copyWith(
            fontSize: 52,
            color: MedoraColors.accent,
            height: 1.05,
          ),
        ),
        Text(
          s.helloIntro,
          style: text.displaySmall?.copyWith(fontSize: 52, height: 1.1),
        ),
        const SizedBox(height: 18),
        Text(
          config.smartBand ? s.introWithBand : s.introNoBand,
          style: text.bodyLarge?.copyWith(
            color: MedoraColors.muted,
            fontSize: 19,
            height: 1.5,
          ),
        ),
      ],
    );

    final choices = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (offline) ...[
          MedoraNotice(
            icon: Icons.cloud_off,
            message: config.manualIntake ? s.offlineFormOnly : s.offlineNothing,
          ),
          const SizedBox(height: 20),
        ],
        // The language first, where the patient looks (the user's request
        // of 2026-10-29); voice then greets in it too.
        const _LanguageChoice(),
        const SizedBox(height: 28),
        Text(
          s.howToStart,
          style: text.bodyMedium?.copyWith(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
          ),
        ),
        const SizedBox(height: 14),
        // Two tiles, a microphone and a keyboard: the way in is clear at a
        // glance, in either language.
        IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (config.voiceIntake)
                Expanded(
                  child: _ModeTile(
                    key: const Key('mode-voice'),
                    icon: Icons.mic_rounded,
                    color: MedoraColors.primary,
                    title: s.speakTile,
                    subtitle: offline
                        ? s.needsInternet
                        : voiceDown
                        ? s.notAvailableNow
                        : s.speakTileSubtitle,
                    onTap: voiceDown || offline
                        ? null
                        : () => _start(context, ref, IntakeMode.voice),
                  ),
                ),
              if (config.voiceIntake && config.manualIntake)
                const SizedBox(width: 16),
              // Typing is done on the patient's own phone, not on this
              // shared screen (fewer hands on it, less infection).
              if (config.manualIntake)
                Expanded(
                  child: _ModeTile(
                    key: const Key('mode-phone'),
                    icon: Icons.qr_code_2_rounded,
                    color: MedoraColors.accent,
                    title: s.usePhoneTile,
                    // Works offline too: the phone reaches this kiosk's
                    // server over the hospital's own Wi-Fi.
                    subtitle: s.usePhoneSubtitle,
                    onTap: () => _start(context, ref, IntakeMode.phone),
                  ),
                ),
            ],
          ),
        ),
        if (config.manualIntake) ...[
          const SizedBox(height: 12),
          // No phone, or no internet: the form on this screen.
          Center(
            child: TextButton.icon(
              key: const Key('mode-manual'),
              onPressed: () => _start(context, ref, IntakeMode.manual),
              icon: const Icon(Icons.keyboard_alt_outlined),
              label: Text(s.typeHereInstead),
            ),
          ),
        ],
      ],
    );

    return MedoraScaffold(
      maxWidth: 1120,
      child: LayoutBuilder(
        builder: (context, constraints) => constraints.maxWidth >= 860
            ? Padding(
                padding: const EdgeInsets.only(top: 36),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Expanded(flex: 11, child: intro),
                    const SizedBox(width: 64),
                    Expanded(flex: 10, child: choices),
                  ],
                ),
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [intro, const SizedBox(height: 36), choices],
              ),
      ),
    );
  }
}

/// One way into the visit: a large tile with a microphone or a keyboard.
class _ModeTile extends StatelessWidget {
  const _ModeTile({
    super.key,
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;

  /// Null shows the tile greyed out and untappable.
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final enabled = onTap != null;
    final color = enabled ? this.color : MedoraColors.muted;
    return Semantics(
      button: true,
      enabled: enabled,
      label: title,
      child: Material(
        color: MedoraColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(22),
          side: BorderSide(
            color: enabled
                ? color.withValues(alpha: 0.35)
                : MedoraColors.border,
            width: 1.5,
          ),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(22),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 30, 20, 26),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 96,
                  height: 96,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: enabled ? color : color.withValues(alpha: 0.12),
                  ),
                  child: Icon(
                    icon,
                    size: 48,
                    color: enabled ? Colors.white : color,
                  ),
                ),
                const SizedBox(height: 18),
                Text(
                  title,
                  textAlign: TextAlign.center,
                  style: text.titleLarge?.copyWith(
                    fontSize: 24,
                    color: enabled ? MedoraColors.text : MedoraColors.muted,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  textAlign: TextAlign.center,
                  style: text.bodyMedium?.copyWith(fontSize: 15),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// English or Malayalam, as two large buttons at the front of the welcome
/// page. The screen, the form, the voice greeting and the report follow it.
class _LanguageChoice extends ConsumerWidget {
  const _LanguageChoice();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final current = ref.watch(languageProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          // Both languages, so either reader finds it.
          '${S.of(context).chooseLanguage.toUpperCase()}'
          '${current == AppLanguage.english ? '  ·  ഭാഷ' : '  ·  LANGUAGE'}',
          style: text.bodyMedium?.copyWith(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
            fontFamilyFallback: MedoraFonts.fallback,
          ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            for (final (i, language) in AppLanguage.values.indexed) ...[
              if (i > 0) const SizedBox(width: 12),
              Expanded(
                child: _LanguageButton(
                  key: Key('welcome-language-${language.code}'),
                  label: language.nativeName,
                  selected: current == language,
                  onTap: () =>
                      ref.read(languageProvider.notifier).set(language),
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }
}

class _LanguageButton extends StatelessWidget {
  const _LanguageButton({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    selected: selected,
    label: label,
    child: Material(
      color: selected ? MedoraColors.primary : MedoraColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(
          color: selected ? MedoraColors.primary : MedoraColors.border,
          width: 1.5,
        ),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                selected ? Icons.check_circle_rounded : Icons.translate_rounded,
                size: 20,
                color: selected ? Colors.white : MedoraColors.primary,
              ),
              const SizedBox(width: 10),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontFamily: MedoraFonts.sans,
                    fontFamilyFallback: MedoraFonts.fallback,
                    fontSize: 19,
                    fontWeight: FontWeight.w700,
                    color: selected ? Colors.white : MedoraColors.text,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
