import 'package:flutter/material.dart';

import '../band/band_service.dart';
import '../l10n/strings.dart';
import '../models/intake.dart';
import '../theme/medora_theme.dart';
import 'medora_scaffold.dart';

/// Band readings as tiles. A value the band has not sent shows as "--",
/// or as "Not measured" once the measurement is over.
class VitalsGrid extends StatelessWidget {
  const VitalsGrid({
    super.key,
    required this.vitals,
    required this.signs,
    this.finished = false,
    this.active,
  });

  final Vitals vitals;

  /// Which vitals to show: those the band measures.
  final List<VitalSign> signs;
  final bool finished;

  /// The vital the band is measuring now, highlighted.
  final VitalSign? active;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final bp = vitals.systolic != null && vitals.diastolic != null
        ? '${vitals.systolic}/${vitals.diastolic}'
        : null;
    final all = {
      VitalSign.heartRate: _VitalTile(
        icon: Icons.favorite,
        label: s.vitalName(VitalSign.heartRate),
        value: vitals.heartRate?.toString(),
        unit: 'bpm',
        finished: finished,
        active: active == VitalSign.heartRate,
      ),
      VitalSign.spo2: _VitalTile(
        icon: Icons.water_drop,
        label: s.vitalName(VitalSign.spo2),
        value: vitals.spo2?.toString(),
        unit: '%',
        finished: finished,
        active: active == VitalSign.spo2,
      ),
      VitalSign.temperature: _VitalTile(
        icon: Icons.thermostat,
        label: s.vitalName(VitalSign.temperature),
        value: vitals.temperatureC?.toStringAsFixed(1),
        unit: '°C',
        finished: finished,
        active: active == VitalSign.temperature,
      ),
      VitalSign.bloodPressure: _VitalTile(
        icon: Icons.speed,
        label: s.vitalName(VitalSign.bloodPressure),
        value: bp,
        unit: 'mmHg',
        finished: finished,
        active: active == VitalSign.bloodPressure,
      ),
    };
    final tiles = [for (final s in signs) all[s]!];
    if (tiles.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 16.0;
        final columns =
            (constraints.maxWidth >= 760
                    ? 4
                    : constraints.maxWidth >= 380
                    ? 2
                    : 1)
                .clamp(1, tiles.length);
        final width = (constraints.maxWidth - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final tile in tiles) SizedBox(width: width, child: tile),
          ],
        );
      },
    );
  }
}

class _VitalTile extends StatelessWidget {
  const _VitalTile({
    required this.icon,
    required this.label,
    required this.value,
    required this.unit,
    required this.finished,
    required this.active,
  });

  final bool finished;
  final bool active;
  final IconData icon;
  final String label;
  final String? value;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final captured = value != null;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        border: Border.all(
          color: active ? MedoraColors.primary : Colors.transparent,
          width: 2,
        ),
      ),
      child: MedoraCard(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  icon,
                  size: 20,
                  color: captured ? MedoraColors.teal : MedoraColors.muted,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.bodyMedium,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            // A long reading ("118/76 mmHg") shrinks rather than overflow.
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: [
                  if (!captured && finished)
                    Text(
                      S.of(context).notMeasured,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    )
                  else ...[
                    Text(
                      value ?? (active ? '…' : '--'),
                      style: TextStyle(
                        fontSize: 30,
                        fontFamily: MedoraFonts.serif,
                        fontWeight: FontWeight.w600,
                        color: captured
                            ? MedoraColors.text
                            : MedoraColors.muted,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(unit, style: Theme.of(context).textTheme.bodyMedium),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
