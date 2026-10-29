import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../l10n/strings.dart';
import '../state/kiosk_context.dart';
import '../state/service_status.dart';
import '../theme/medora_theme.dart';

/// The four steps shown in the top bar. `null` hides the indicator (welcome).
enum FlowStep { intake, vitals, review, report }

class MedoraScaffold extends StatelessWidget {
  const MedoraScaffold({
    super.key,
    required this.child,
    this.step,
    this.maxWidth = 920,
    this.languageSwitch = true,
  });

  final Widget child;
  final FlowStep? step;
  final double maxWidth;

  /// Whether the top bar lets the patient change language. Off where a
  /// change would not take effect (a conversation already in a language).
  final bool languageSwitch;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              MedoraColors.background,
              MedoraColors.background,
              MedoraColors.background,
            ],
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              _TopBar(step: step, languageSwitch: languageSwitch),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 32,
                  ),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: BoxConstraints(maxWidth: maxWidth),
                      child: child,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TopBar extends ConsumerWidget {
  const _TopBar({required this.step, required this.languageSwitch});

  final FlowStep? step;
  final bool languageSwitch;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Until the first answer arrives, assume online: no chip flashes up.
    final offline = !(ref.watch(serviceStatusProvider).value?.online ?? true);
    final preview = ref.watch(kioskPreviewProvider);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
      decoration: const BoxDecoration(
        color: Color(0xCCFFFFFF),
        border: Border(bottom: BorderSide(color: MedoraColors.border)),
      ),
      child: Row(
        children: [
          const BrandMark(size: 36),
          const SizedBox(width: 10),
          Text('Medora', style: Theme.of(context).textTheme.titleLarge),
          if (offline) ...[
            const SizedBox(width: 14),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: MedoraColors.warning.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.cloud_off,
                    size: 16,
                    color: MedoraColors.warning,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    S.of(context).offlineMode,
                    style: const TextStyle(
                      color: MedoraColors.warning,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (preview != null) ...[
            const SizedBox(width: 14),
            // Only ever shown to staff: a real kiosk has no preview and no
            // way back to the back office.
            ActionChip(
              avatar: const Icon(Icons.arrow_back, size: 16),
              label: Text('Preview: ${preview.clientName}  ·  Back office'),
              onPressed: () {
                ref.read(kioskPreviewProvider.notifier).stop();
                GoRouter.of(context).go('/');
              },
            ),
          ],
          const Spacer(),
          if (step != null) _StepIndicator(current: step!),
          if (languageSwitch) ...[
            const SizedBox(width: 16),
            const _LanguageToggle(),
          ],
        ],
      ),
    );
  }
}

class _StepIndicator extends ConsumerWidget {
  const _StepIndicator({required this.current});

  final FlowStep current;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = S.of(context);
    final labels = {
      FlowStep.intake: s.stepIntake,
      FlowStep.vitals: s.stepVitals,
      FlowStep.review: s.stepReview,
      FlowStep.report: s.stepReport,
    };
    final narrow = MediaQuery.sizeOf(context).width < 640;
    final band = ref.watch(kioskConfigProvider).smartBand;
    final steps = [
      for (final step in FlowStep.values)
        if (band || step != FlowStep.vitals) step,
    ];
    final currentIndex = steps.indexOf(current);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final (i, step) in steps.indexed) ...[
          if (i > 0)
            Container(
              width: narrow ? 10 : 24,
              height: 2,
              margin: const EdgeInsets.symmetric(horizontal: 6),
              color: i <= currentIndex
                  ? MedoraColors.primary
                  : MedoraColors.border,
            ),
          _StepDot(
            number: i + 1,
            label: narrow && step != current ? null : labels[step]!,
            done: i < currentIndex,
            active: step == current,
          ),
        ],
      ],
    );
  }
}

class _StepDot extends StatelessWidget {
  const _StepDot({
    required this.number,
    required this.label,
    required this.done,
    required this.active,
  });

  final int number;
  final String? label;
  final bool done;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final reached = done || active;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 28,
          height: 28,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: reached ? MedoraColors.primary : MedoraColors.surface,
            border: Border.all(
              color: reached ? MedoraColors.primary : MedoraColors.border,
            ),
          ),
          child: done
              ? const Icon(Icons.check, size: 16, color: Colors.white)
              : Text(
                  '$number',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: active ? Colors.white : MedoraColors.muted,
                  ),
                ),
        ),
        if (label != null) ...[
          const SizedBox(width: 8),
          Text(
            label!,
            style: TextStyle(
              fontSize: 15,
              fontWeight: active ? FontWeight.w700 : FontWeight.w500,
              color: reached ? MedoraColors.text : MedoraColors.muted,
            ),
          ),
        ],
      ],
    );
  }
}

/// White surface with a soft, deep shadow.
class MedoraCard extends StatelessWidget {
  const MedoraCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(24),
  });

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: MedoraColors.surface,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: MedoraColors.border),
        boxShadow: MedoraTheme.cardShadow,
      ),
      // Ink-based children (list tiles, switches) paint on this Material;
      // the card's own colour would otherwise hide their ink.
      child: Material(type: MaterialType.transparency, child: child),
    );
  }
}

/// Inline notice for states the patient or developer needs to know about.
class MedoraNotice extends StatelessWidget {
  const MedoraNotice({
    super.key,
    required this.icon,
    required this.message,
    this.color = MedoraColors.warning,
  });

  final IconData icon;
  final String message;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 22),
          const SizedBox(width: 12),
          Expanded(
            child: Text(message, style: TextStyle(color: color, fontSize: 15)),
          ),
        ],
      ),
    );
  }
}

/// Medora's mark: the shield on the brand gradient.
class BrandMark extends StatelessWidget {
  const BrandMark({super.key, this.size = 40});

  final double size;

  @override
  Widget build(BuildContext context) {
    // A serif monogram on pine with a terracotta full stop: "M."
    // The same shape as the kiosk's Dr. Medora, never a stock medical icon.
    return Container(
      width: size,
      height: size,
      decoration: const BoxDecoration(
        shape: BoxShape.circle,
        color: MedoraColors.primary,
      ),
      alignment: Alignment.center,
      child: Text.rich(
        TextSpan(
          children: [
            const TextSpan(text: 'M'),
            TextSpan(
              text: '.',
              style: TextStyle(
                color: MedoraColors.accent,
                fontSize: size * 0.56,
              ),
            ),
          ],
        ),
        style: TextStyle(
          fontFamily: MedoraFonts.serif,
          fontWeight: FontWeight.w600,
          fontSize: size * 0.48,
          height: 1.05,
          color: MedoraColors.background,
        ),
      ),
    );
  }
}

/// English or Malayalam, from the top bar.
class _LanguageToggle extends ConsumerWidget {
  const _LanguageToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = ref.watch(languageProvider);
    final next = current == AppLanguage.english
        ? AppLanguage.malayalam
        : AppLanguage.english;
    return TextButton.icon(
      key: const Key('language-toggle'),
      onPressed: () => ref.read(languageProvider.notifier).set(next),
      icon: const Icon(Icons.translate_rounded, size: 20),
      label: Text(next.nativeName),
    );
  }
}
