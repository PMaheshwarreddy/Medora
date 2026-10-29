import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../band/band_service.dart';
import '../band/drivers/simulator/simulator_band.dart';
import '../l10n/strings.dart';
import '../theme/medora_theme.dart';

/// The band simulator's controls (`band/drivers/simulator/`): a slider for
/// each vital it reports, and ready-made sets. Shown only while the
/// simulator is the kiosk's band (`band/band_registry.dart`); with the real
/// band it shows nothing.
class SimulatorPanel extends ConsumerWidget {
  const SimulatorPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(bandServiceProvider) is! SimulatorBand) {
      return const SizedBox.shrink();
    }
    final v = ref.watch(simulatorProvider);
    final control = ref.read(simulatorProvider.notifier);
    final text = Theme.of(context).textTheme;
    final s = S.of(context);

    return Container(
      margin: const EdgeInsets.only(bottom: 20),
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      decoration: BoxDecoration(
        color: MedoraColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: MedoraColors.border),
      ),
      child: Material(
        type: MaterialType.transparency,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.tune_rounded, color: MedoraColors.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(s.simulatorTitle, style: text.titleMedium),
                      Text(
                        s.simulatorHint,
                        style: text.bodyMedium?.copyWith(fontSize: 13.5),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final (name, preset) in simulatorPresets)
                  ActionChip(
                    key: Key('preset-$name'),
                    label: Text(name),
                    onPressed: () => control.set(preset),
                  ),
              ],
            ),
            const SizedBox(height: 6),
            _Slider(
              key: const Key('slider-heartRate'),
              label: s.vitalName(VitalSign.heartRate),
              value: v.heartRate.toDouble(),
              min: 30,
              max: 200,
              shown: '${v.heartRate} bpm',
              onChanged: (x) => control.set(v.copyWith(heartRate: x.round())),
            ),
            _Slider(
              key: const Key('slider-spo2'),
              label: s.vitalName(VitalSign.spo2),
              value: v.spo2.toDouble(),
              min: 70,
              max: 100,
              shown: '${v.spo2}%',
              onChanged: (x) => control.set(v.copyWith(spo2: x.round())),
            ),
            _Slider(
              key: const Key('slider-temperature'),
              label: s.vitalName(VitalSign.temperature),
              value: v.temperatureC,
              min: 34,
              max: 42,
              divisions: 80,
              shown: '${v.temperatureC.toStringAsFixed(1)} °C',
              onChanged: (x) =>
                  control.set(v.copyWith(temperatureC: (x * 10).round() / 10)),
            ),
            _Slider(
              key: const Key('slider-systolic'),
              label: s.systolic,
              value: v.systolic.toDouble(),
              min: 70,
              max: 220,
              shown: '${v.systolic} mmHg',
              onChanged: (x) {
                final systolic = x.round();
                control.set(
                  v.copyWith(
                    systolic: systolic,
                    // Keep the pair possible: diastolic below systolic.
                    diastolic: v.diastolic >= systolic
                        ? systolic - 10
                        : v.diastolic,
                  ),
                );
              },
            ),
            _Slider(
              key: const Key('slider-diastolic'),
              label: s.diastolic,
              value: v.diastolic.toDouble(),
              min: 40,
              max: 140,
              shown: '${v.diastolic} mmHg',
              onChanged: (x) => control.set(
                v.copyWith(diastolic: x.round().clamp(40, v.systolic - 10)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Slider extends StatelessWidget {
  const _Slider({
    super.key,
    required this.label,
    required this.value,
    required this.min,
    required this.max,
    required this.shown,
    required this.onChanged,
    this.divisions,
  });

  final String label;
  final double value;
  final double min;
  final double max;
  final int? divisions;
  final String shown;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      SizedBox(
        width: 170,
        child: Text(label, style: const TextStyle(fontSize: 14)),
      ),
      Expanded(
        child: Slider(
          value: value.clamp(min, max),
          min: min,
          max: max,
          divisions: divisions ?? (max - min).round(),
          label: shown,
          onChanged: onChanged,
        ),
      ),
      SizedBox(
        width: 84,
        child: Text(
          shown,
          textAlign: TextAlign.right,
          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
        ),
      ),
    ],
  );
}
