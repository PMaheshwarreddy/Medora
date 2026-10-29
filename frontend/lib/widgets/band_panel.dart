import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../band/band_service.dart';
import '../l10n/strings.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import 'medora_scaffold.dart';
import 'simulator_panel.dart';
import 'vitals_grid.dart';

/// Takes the patient's vitals with the kiosk's band: what to do, a start
/// button (the browser needs a tap to reach Bluetooth), live progress, and
/// the readings. Readings go into the intake as they arrive.
class BandPanel extends ConsumerStatefulWidget {
  const BandPanel({super.key, required this.onFinished, this.onSkip});

  /// How long the finished readings stay up before [onFinished].
  static const handOverDelay = Duration(milliseconds: 2500);

  /// Called when a measurement ends with at least one reading.
  final ValueChanged<Vitals> onFinished;

  /// Offered when the band cannot be used or failed; null hides it.
  final VoidCallback? onSkip;

  @override
  ConsumerState<BandPanel> createState() => _BandPanelState();
}

class _BandPanelState extends ConsumerState<BandPanel> {
  StreamSubscription<BandStatus>? _run;
  BandStatus? _status;
  DateTime? _since;
  Timer? _tick;
  Timer? _handOver;

  @override
  void dispose() {
    _run?.cancel();
    _tick?.cancel();
    _handOver?.cancel();
    super.dispose();
  }

  void _start() {
    final band = ref.read(bandServiceProvider);
    // Readings from an earlier attempt must not mix with these.
    ref.read(intakeProvider.notifier).setVitals(const Vitals());
    _run?.cancel();
    _tick?.cancel();
    _handOver?.cancel();
    _tick = Timer.periodic(
      const Duration(milliseconds: 250),
      (_) => setState(() {}),
    );
    setState(() => _status = const BandStatus(BandPhase.connecting));
    _run = band.measure().listen((status) {
      if (status.current != _status?.current) _since = DateTime.now();
      setState(() => _status = status);
      if (status.vitals.hasAny) {
        ref.read(intakeProvider.notifier).setVitals(status.vitals);
      }
      if (status.phase == BandPhase.done) {
        _tick?.cancel();
        // Leave the readings on screen for a moment before moving on, so
        // the patient sees that the measurement worked.
        _handOver?.cancel();
        _handOver = Timer(BandPanel.handOverDelay, () {
          if (mounted) widget.onFinished(status.vitals);
        });
      } else if (status.phase == BandPhase.failed) {
        _tick?.cancel();
      }
    }, onDone: () => _tick?.cancel());
  }

  /// Stops the band and goes back to the start.
  void _cancel() {
    _run?.cancel();
    _run = null;
    _tick?.cancel();
    _handOver?.cancel();
    ref.read(intakeProvider.notifier).setVitals(const Vitals());
    setState(() => _status = null);
  }

  @override
  Widget build(BuildContext context) {
    final band = ref.watch(bandServiceProvider);
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final status = _status;

    if (!band.isAvailable) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MedoraNotice(
            icon: Icons.bluetooth_disabled,
            message: s.bandMessage(band.unavailableReason),
          ),
          if (widget.onSkip != null) ...[
            const SizedBox(height: 16),
            _SkipButton(onPressed: widget.onSkip!),
          ],
        ],
      );
    }

    final phase = status?.phase;
    final measuring = phase == BandPhase.measuring;
    final busy =
        phase == BandPhase.connecting ||
        phase == BandPhase.preparing ||
        measuring;
    final left = _secondsLeft(status);

    final (
      IconData icon,
      Color color,
      String title,
      String detail,
    ) = switch (phase) {
      null => (
        Icons.touch_app_rounded,
        MedoraColors.primary,
        s.putOnBand,
        s.language == AppLanguage.english
            ? band.wearInstruction
            : s.wearInstruction,
      ),
      BandPhase.connecting => (
        Icons.bluetooth_searching_rounded,
        MedoraColors.primary,
        s.connectingBand,
        s.connectingDetail,
      ),
      BandPhase.preparing => (
        Icons.bluetooth_connected_rounded,
        MedoraColors.primary,
        s.preparingBand,
        s.connectedTo(status!.deviceName ?? s.bandNoun),
      ),
      BandPhase.measuring => (
        Icons.monitor_heart_rounded,
        MedoraColors.violet,
        s.measuring(status!.current!),
        left == null ? s.keepStill : s.keepStillUpTo(left),
      ),
      BandPhase.done => (
        Icons.check_rounded,
        MedoraColors.teal,
        s.vitalsTaken,
        status!.missed.isEmpty
            ? s.allReadingsIn
            : s.couldNotRead(status.missed),
      ),
      BandPhase.failed => (
        Icons.error_outline_rounded,
        MedoraColors.warning,
        s.didNotWork,
        status!.message == null
            ? s.bandStopped
            : s.bandMessage(status.message!),
      ),
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // The simulator's sliders, when it is the kiosk's band; set before
        // measuring, or changed to measure again.
        if (phase == null || phase == BandPhase.done) const SimulatorPanel(),
        MedoraCard(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Container(
                    width: 58,
                    height: 58,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: MedoraTheme.tint(color),
                      boxShadow: [
                        BoxShadow(
                          color: color.withValues(alpha: 0.3),
                          blurRadius: 16,
                          offset: const Offset(0, 6),
                        ),
                      ],
                    ),
                    child: Icon(icon, color: Colors.white, size: 30),
                  ),
                  const SizedBox(width: 18),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title, style: text.titleLarge),
                        const SizedBox(height: 4),
                        Text(
                          detail,
                          style: text.bodyLarge?.copyWith(
                            fontSize: 16,
                            color: MedoraColors.muted,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              if (busy) ...[
                const SizedBox(height: 20),
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: LinearProgressIndicator(
                    minHeight: 8,
                    value: measuring ? _overall(status!) : null,
                    backgroundColor: MedoraColors.border,
                  ),
                ),
                if (measuring) ...[
                  const SizedBox(height: 10),
                  _Steps(status: status!),
                ],
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(onPressed: _cancel, child: Text(s.cancel)),
                ),
              ],
              if (phase == null || phase == BandPhase.failed) ...[
                const SizedBox(height: 22),
                FilledButton.icon(
                  onPressed: _start,
                  icon: Icon(
                    phase == null
                        ? Icons.play_arrow_rounded
                        : Icons.refresh_rounded,
                  ),
                  label: Text(phase == null ? s.startMeasuring : s.tryAgain),
                ),
              ],
              if (phase == BandPhase.done) ...[
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: _start,
                    icon: const Icon(Icons.refresh_rounded),
                    label: Text(s.measureAgain),
                  ),
                ),
              ],
              if (phase == BandPhase.failed && widget.onSkip != null) ...[
                const SizedBox(height: 8),
                _SkipButton(onPressed: widget.onSkip!),
              ],
            ],
          ),
        ),
        const SizedBox(height: 20),
        VitalsGrid(
          // What the band said it can do, once it has; until then, what
          // this band model measures.
          signs: status != null && status.supported.isNotEmpty
              ? [
                  for (final s in band.measures)
                    if (status.supported.contains(s)) s,
                ]
              : band.measures,
          vitals: status?.vitals ?? const Vitals(),
          finished: phase == BandPhase.done,
          active: status?.current,
        ),
      ],
    );
  }

  int? _secondsLeft(BandStatus? status) {
    final window = status?.window;
    final since = _since;
    if (window == null || since == null) return null;
    final left = window - DateTime.now().difference(since);
    return left.isNegative ? 0 : (left.inMilliseconds / 1000).ceil();
  }

  /// How far through all of this band's vitals the measurement is.
  double _overall(BandStatus status) {
    final order = [
      for (final s in VitalSign.values)
        if (status.supported.contains(s)) s,
    ];
    final index = order.indexOf(status.current!);
    if (order.isEmpty || index < 0) return 0;
    final window = status.window;
    final since = _since;
    final part = window == null || since == null
        ? 0.0
        : (DateTime.now().difference(since).inMilliseconds /
                  window.inMilliseconds)
              .clamp(0.0, 1.0);
    return (index + part) / order.length;
  }
}

/// Which vitals are done, being measured, or still to come.
class _Steps extends StatelessWidget {
  const _Steps({required this.status});

  final BandStatus status;

  @override
  Widget build(BuildContext context) {
    final order = [
      for (final s in VitalSign.values)
        if (status.supported.contains(s)) s,
    ];
    final at = order.indexOf(status.current!);
    return Wrap(
      spacing: 16,
      runSpacing: 6,
      children: [
        for (final (i, sign) in order.indexed)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                i < at
                    ? (status.missed.contains(sign)
                          ? Icons.remove_circle_outline
                          : Icons.check_circle_rounded)
                    : i == at
                    ? Icons.radio_button_checked_rounded
                    : Icons.radio_button_unchecked_rounded,
                size: 18,
                color: i <= at ? MedoraColors.primary : MedoraColors.muted,
              ),
              const SizedBox(width: 6),
              Text(
                S.of(context).vitalName(sign),
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: i == at ? FontWeight.w700 : FontWeight.w500,
                  color: i <= at ? MedoraColors.text : MedoraColors.muted,
                ),
              ),
            ],
          ),
      ],
    );
  }
}

class _SkipButton extends StatelessWidget {
  const _SkipButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => Align(
    alignment: Alignment.centerLeft,
    child: TextButton(
      onPressed: onPressed,
      child: Text(S.of(context).continueWithoutVitals),
    ),
  );
}
