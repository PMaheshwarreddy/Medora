import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/intake.dart';
import '../../band_service.dart';

/// The vitals the simulator reports, set on its sliders.
class SimulatedValues {
  const SimulatedValues({
    this.heartRate = 76,
    this.spo2 = 98,
    this.temperatureC = 36.8,
    this.systolic = 118,
    this.diastolic = 76,
  });

  final int heartRate;
  final int spo2;
  final double temperatureC;
  final int systolic;
  final int diastolic;

  SimulatedValues copyWith({
    int? heartRate,
    int? spo2,
    double? temperatureC,
    int? systolic,
    int? diastolic,
  }) => SimulatedValues(
    heartRate: heartRate ?? this.heartRate,
    spo2: spo2 ?? this.spo2,
    temperatureC: temperatureC ?? this.temperatureC,
    systolic: systolic ?? this.systolic,
    diastolic: diastolic ?? this.diastolic,
  );
}

/// Ready-made sets of vitals, one tap each.
const simulatorPresets = <(String, SimulatedValues)>[
  ('Normal', SimulatedValues()),
  (
    'Fever',
    SimulatedValues(
      heartRate: 104,
      spo2: 97,
      temperatureC: 38.9,
      systolic: 116,
      diastolic: 74,
    ),
  ),
  (
    'Low oxygen',
    SimulatedValues(
      heartRate: 112,
      spo2: 88,
      temperatureC: 37.4,
      systolic: 124,
      diastolic: 80,
    ),
  ),
  (
    'High BP',
    SimulatedValues(
      heartRate: 88,
      spo2: 97,
      temperatureC: 36.9,
      systolic: 182,
      diastolic: 122,
    ),
  ),
  (
    'Low BP',
    SimulatedValues(
      heartRate: 126,
      spo2: 94,
      temperatureC: 36.2,
      systolic: 84,
      diastolic: 52,
    ),
  ),
  (
    'Slow heart',
    SimulatedValues(
      heartRate: 44,
      spo2: 97,
      temperatureC: 36.6,
      systolic: 110,
      diastolic: 70,
    ),
  ),
];

class SimulatorController extends Notifier<SimulatedValues> {
  @override
  SimulatedValues build() => const SimulatedValues();

  void set(SimulatedValues values) => state = values;
}

/// The values the simulator reports, as set on its sliders.
final simulatorProvider =
    NotifierProvider<SimulatorController, SimulatedValues>(
      SimulatorController.new,
    );

/// The band simulator, picked in `band_registry.dart` in place of the real
/// band: it reports what the sliders on the vitals screen say, as a band
/// would, through the same [BandService] interface, so the rest of the
/// flow (vitals rules, report, PDF, voice agent) is unchanged. It takes all
/// four vitals, so temperature and blood pressure can be tried too; the
/// real Y26 band takes heart rate and SpO2 only.
class SimulatorBand implements BandService {
  SimulatorBand(this._values, {this.step = const Duration(milliseconds: 900)});

  /// Read at measurement time, so the latest slider values are used.
  final SimulatedValues Function() _values;

  /// How long each "measurement" takes, so the screen shows progress.
  final Duration step;

  @override
  String get deviceNoun => 'band';

  @override
  String get wearInstruction =>
      'Set the vitals on the sliders, then tap Start measuring.';

  @override
  List<VitalSign> get measures => const [
    VitalSign.heartRate,
    VitalSign.spo2,
    VitalSign.temperature,
    VitalSign.bloodPressure,
  ];

  @override
  bool get isAvailable => true;

  @override
  String get unavailableReason => '';

  @override
  Stream<BandStatus> measure() async* {
    final v = _values();
    final supported = measures.toSet();
    yield const BandStatus(BandPhase.connecting);
    await Future<void>.delayed(step);
    yield BandStatus(
      BandPhase.preparing,
      supported: supported,
      deviceName: 'Band simulator',
    );
    var vitals = const Vitals();
    for (final sign in VitalSign.values.where(supported.contains)) {
      yield BandStatus(
        BandPhase.measuring,
        vitals: vitals,
        supported: supported,
        current: sign,
        window: step,
      );
      await Future<void>.delayed(step);
      vitals = switch (sign) {
        VitalSign.heartRate => vitals.copyWith(heartRate: v.heartRate),
        VitalSign.spo2 => vitals.copyWith(spo2: v.spo2),
        VitalSign.temperature => vitals.copyWith(temperatureC: v.temperatureC),
        VitalSign.bloodPressure => vitals.copyWith(
          systolic: v.systolic,
          diastolic: v.diastolic,
        ),
      };
    }
    yield BandStatus(BandPhase.done, vitals: vitals, supported: supported);
  }
}
