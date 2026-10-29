import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:medora/band/band_service.dart';
import 'package:medora/band/drivers/simulator/simulator_band.dart';
import 'package:medora/models/intake.dart';
import 'package:medora/state/intake_controller.dart';
import 'package:medora/widgets/band_panel.dart';

void main() {
  test('the simulator reports the values set on its sliders', () async {
    final band = SimulatorBand(
      () => simulatorPresets.firstWhere((p) => p.$1 == 'Fever').$2,
      step: Duration.zero,
    );
    final statuses = await band.measure().toList();
    expect(statuses.first.phase, BandPhase.connecting);
    // It goes through the same steps a real band does, one vital at a time.
    expect(
      [
        for (final s in statuses)
          if (s.phase == BandPhase.measuring) s.current,
      ],
      [
        VitalSign.heartRate,
        VitalSign.spo2,
        VitalSign.bloodPressure,
        VitalSign.temperature,
      ],
    );
    final done = statuses.last;
    expect(done.phase, BandPhase.done);
    expect(done.vitals.temperatureC, 38.9);
    expect(done.vitals.heartRate, 104);
    expect((done.vitals.systolic, done.vitals.diastolic), (116, 74));
    // All four, so temperature and blood pressure can be tried too.
    expect(band.measures.length, 4);
  });

  test('the simulator is the kiosk band (band_registry.dart)', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    expect(container.read(bandServiceProvider), isA<SimulatorBand>());
  });

  testWidgets('the sliders set what the measurement reports', (tester) async {
    tester.view.physicalSize = const Size(1280, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final container = ProviderContainer(
      overrides: [
        // Instant steps, so the test need not wait for each "measurement".
        bandServiceProvider.overrideWith(
          (ref) => SimulatorBand(
            () => ref.read(simulatorProvider),
            step: const Duration(milliseconds: 10),
          ),
        ),
      ],
    );
    addTearDown(container.dispose);
    Vitals? finished;
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: BandPanel(onFinished: (v) => finished = v),
            ),
          ),
        ),
      ),
    );

    // One slider per reading: heart rate, SpO2, temperature, BP upper/lower.
    expect(find.byType(Slider), findsNWidgets(5));
    await tester.tap(find.byKey(const Key('preset-High BP')));
    await tester.pump();
    expect(container.read(simulatorProvider).systolic, 182);
    expect(find.text('182 mmHg'), findsOneWidget);

    // Drag the temperature up: a fever.
    await tester.drag(
      find.byKey(const Key('slider-temperature')).last,
      const Offset(400, 0),
    );
    await tester.pump();
    final temperature = container.read(simulatorProvider).temperatureC;
    expect(temperature, greaterThan(38));

    await tester.tap(find.text('Start measuring'));
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    // The readings reach the visit like a real band's do.
    final vitals = container.read(intakeProvider).vitals;
    expect(vitals.systolic, 182);
    expect(vitals.temperatureC, temperature);
    await tester.pump(BandPanel.handOverDelay);
    expect(finished?.temperatureC, temperature);
    // The sliders come back after the measurement, to measure again.
    expect(find.byType(Slider), findsNWidgets(5));
  });
}
