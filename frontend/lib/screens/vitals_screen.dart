import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../band/band_service.dart';
import '../l10n/strings.dart';
import '../state/intake_controller.dart';
import '../widgets/band_panel.dart';
import '../widgets/medora_scaffold.dart';

/// Vitals step of the manual flow. Readings come from the band only.
class VitalsScreen extends ConsumerWidget {
  const VitalsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final measured = ref.watch(intakeProvider.select((s) => s.vitals.hasAny));
    final band = ref.watch(bandServiceProvider);
    // Up to 30 s per vital, plus connecting.
    final seconds = band.measures.length * 30 + 10;
    return MedoraScaffold(
      step: FlowStep.vitals,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(s.vitalsTitle, style: text.headlineSmall),
          const SizedBox(height: 6),
          Text(
            s.vitalsTakes(seconds <= 90 ? 1 : (seconds / 60).round()),
            style: text.bodyMedium,
          ),
          const SizedBox(height: 24),
          BandPanel(
            onFinished: (_) {},
            onSkip: () => context.go('/kiosk/review'),
          ),
          const SizedBox(height: 28),
          FilledButton(
            onPressed: measured ? () => context.go('/kiosk/review') : null,
            child: Text(s.continueToReview),
          ),
        ],
      ),
    );
  }
}
