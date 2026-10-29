import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:medora/band/band_service.dart';
import 'package:medora/band/ble/ble_central.dart';
import 'package:medora/band/drivers/qring/qring_band.dart';
import 'package:medora/band/drivers/qring/qring_protocol.dart';

/// A QRing that answers like the real one: the time-sync reply carries its
/// capabilities, and each measurement start is followed by [readings].
class FakeRing implements BleConnection {
  FakeRing({
    this.capabilities = const [1, 0, 0, 0x06],
    Map<int, List<List<int>>>? readings,
    this.answersSetTime = true,
  }) : readings =
           readings ??
           {
             typeHeartRate: [
               [typeHeartRate, 0, 0], // warming up: no value yet
               [typeHeartRate, 0, 72],
             ],
             typeSpo2: [
               [typeSpo2, 0, 96],
               [typeSpo2, 0, 97],
             ],
             typeBloodPressure: [
               [typeBloodPressure, 0, 0, 118, 76],
             ],
             typeBodyTemperature: [
               [typeBodyTemperature, 0, 168], // 20 + 16.8 °C
             ],
           };

  final List<int> capabilities;
  final Map<int, List<List<int>>> readings;
  final bool answersSetTime;
  final written = <Uint8List>[];
  final _out = StreamController<Uint8List>.broadcast();
  final _dropped = Completer<void>();
  bool closed = false;

  @override
  String get deviceName => 'Q_RING';

  @override
  Stream<Uint8List> get notifications => _out.stream;

  @override
  Future<void> get disconnected => _dropped.future;

  @override
  Future<void> write(Uint8List data) async {
    written.add(data);
    if (data[0] == cmdSetTime && answersSetTime) {
      _send(packet(cmdSetTime, capabilities));
    } else if (data[0] == cmdStartMeasure) {
      for (final r in readings[data[1]] ?? const <List<int>>[]) {
        _send(packet(cmdStartMeasure, r));
      }
    }
  }

  void _send(Uint8List bytes) =>
      Timer(const Duration(milliseconds: 2), () => _out.add(bytes));

  void drop() => _dropped.complete();

  @override
  void close() => closed = true;
}

class FakeCentral implements BleCentral {
  FakeCentral(this.ring, {this.error});

  final FakeRing ring;
  final BleException? error;

  @override
  bool get isSupported => true;

  @override
  String get unsupportedReason => '';

  @override
  Future<BleConnection> connect({
    required List<BleFilter> filters,
    required String service,
    required String writeCharacteristic,
    required String notifyCharacteristic,
  }) async {
    if (error != null) throw error!;
    expect(service, serviceUuid);
    expect(filters.first.company, advertisedCompany);
    return ring;
  }
}

const fast = QRingTiming(
  settle: Duration(milliseconds: 1),
  reply: Duration(milliseconds: 40),
  window: Duration(milliseconds: 30),
  gap: Duration(milliseconds: 1),
);

/// A band model with every sensor, so each vital can be exercised.
QRingBand everything(BleCentral ble) =>
    QRingBand(ble, timing: fast, measures: VitalSign.values);

Future<List<BandStatus>> run(FakeRing ring, {BleException? error}) =>
    everything(FakeCentral(ring, error: error)).measure().toList();

void main() {
  group('protocol, as in the SDK', () {
    test('packets are 16 bytes with a summed checksum', () {
      expect(startMeasure(typeHeartRate), [
        0x69, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x6A, //
      ]);
      // Blood oxygen and later types carry 25 in BCD.
      expect(startMeasure(typeSpo2).sublist(0, 4), [0x69, 3, 0x25, 0]);
      expect(startMeasure(typeSpo2).last, (0x69 + 3 + 0x25) & 0xFF);
      expect(stopMeasure(typeBloodPressure, 120, 80).sublist(0, 4), [
        0x6A,
        2,
        120,
        80,
      ]);
      expect(stopMeasure(typeBloodPressure, 120, 80).last, 308 & 0xFF);
    });

    test('the time is sent in BCD, with the language last', () {
      final bytes = setTime(DateTime(2026, 10, 15, 9, 5, 7));
      expect(bytes.sublist(0, 8), [1, 0x26, 0x10, 0x15, 0x09, 0x05, 0x07, 1]);
    });

    test('replies are checked and decoded', () {
      final caps = RingCapabilities.from(
        RingPacket.parse(packet(cmdSetTime, [1, 0, 0, 0x02]))!,
      );
      expect(
        (caps.temperature, caps.spo2, caps.bloodPressure),
        (true, true, false),
      );

      final reading = MeasureReading.from(
        RingPacket.parse(packet(cmdStartMeasure, [11, 0, 168]))!,
      );
      expect(reading.temperatureC, 36.8);

      final corrupt = packet(cmdStartMeasure, [1, 0, 72])..[3] = 73;
      expect(RingPacket.parse(corrupt), isNull);
      expect(RingPacket.parse(Uint8List(10)), isNull);

      final refused = packet(cmdStartMeasure | 0x80, [1, 0, 0]);
      expect(RingPacket.parse(refused)!.refused, isTrue);
      expect(RingPacket.parse(refused)!.command, cmdStartMeasure);
    });
  });

  group('the ring driver', () {
    test('measures everything the ring supports, in order', () async {
      final ring = FakeRing();
      final statuses = await run(ring);

      expect(statuses.first.phase, BandPhase.connecting);
      final last = statuses.last;
      expect(last.phase, BandPhase.done);
      expect(last.supported, VitalSign.values.toSet());
      expect(last.missed, isEmpty);
      expect(
        (
          last.vitals.heartRate,
          last.vitals.spo2,
          last.vitals.systolic,
          last.vitals.diastolic,
          last.vitals.temperatureC,
        ),
        (72, 97, 118, 76, 36.8),
      );
      // Measured one at a time, each stopped with its result.
      expect(ring.written.first[0], cmdSetTime);
      final commands = [
        for (final w in ring.written.skip(1)) (w[0], w[1], w[2], w[3]),
      ];
      expect(commands, [
        (0x69, typeHeartRate, 0, 0),
        (0x6A, typeHeartRate, 72, 0),
        (0x69, typeSpo2, 0x25, 0),
        (0x6A, typeSpo2, 97, 0),
        (0x69, typeBloodPressure, 0, 0),
        (0x6A, typeBloodPressure, 118, 76),
        (0x69, typeBodyTemperature, 0x25, 0),
        (0x6A, typeBodyTemperature, 0, 0),
      ]);
      expect(ring.closed, isTrue);
    });

    test('the Y26 band: heart rate and SpO2 only, by default', () async {
      final band = QRingBand(FakeCentral(FakeRing()), timing: fast);
      expect(band.measures, [VitalSign.heartRate, VitalSign.spo2]);
      final last = (await band.measure().toList()).last;
      expect(last.phase, BandPhase.done);
      expect(last.supported, {VitalSign.heartRate, VitalSign.spo2});
      expect(last.vitals.systolic, isNull);
      expect(last.vitals.temperatureC, isNull);
    });

    test('only the vitals the ring has hardware for', () async {
      final statuses = await run(FakeRing(capabilities: const [0, 0, 0, 0]));
      expect(statuses.last.phase, BandPhase.done);
      expect(statuses.last.supported, {VitalSign.heartRate});
      expect(statuses.last.vitals.spo2, isNull);
    });

    test('impossible readings and refusals are not kept', () async {
      final statuses = await run(
        FakeRing(
          readings: {
            typeHeartRate: [
              [typeHeartRate, 0, 255],
            ],
            typeSpo2: [
              [typeSpo2, 1, 97], // the ring's error code: not worn
            ],
            typeBloodPressure: [
              [typeBloodPressure, 0, 0, 60, 90], // diastolic above systolic
            ],
            typeBodyTemperature: [
              [typeBodyTemperature, 0, 170],
            ],
          },
        ),
      );
      final last = statuses.last;
      expect(last.phase, BandPhase.done);
      expect(last.missed, {
        VitalSign.heartRate,
        VitalSign.spo2,
        VitalSign.bloodPressure,
      });
      expect(last.vitals.heartRate, isNull);
      expect(last.vitals.spo2, isNull);
      expect(last.vitals.systolic, isNull);
      expect(last.vitals.temperatureC, 37.0);
    });

    test('a ring that reads nothing is a failure, with advice', () async {
      final statuses = await run(FakeRing(readings: const {}));
      expect(statuses.last.phase, BandPhase.failed);
      expect(statuses.last.message, contains('skin'));
    });

    test('a ring that does not answer is a failure', () async {
      final statuses = await run(FakeRing(answersSetTime: false));
      expect(statuses.last.phase, BandPhase.failed);
      expect(statuses.last.message, contains('did not respond'));
    });

    test('no ring chosen', () async {
      final statuses = await run(
        FakeRing(),
        error: const BleException('No device was chosen.', cancelled: true),
      );
      expect(statuses.last.phase, BandPhase.failed);
      expect(statuses.last.message, 'No device was chosen.');
    });

    test('a dropped link ends the measurement', () async {
      final ring = FakeRing(readings: const {});
      final band = everything(FakeCentral(ring));
      final statuses = <BandStatus>[];
      final done = Completer<void>();
      band.measure().listen(statuses.add, onDone: done.complete);
      await Future<void>.delayed(const Duration(milliseconds: 15));
      ring.drop();
      await done.future;
      expect(statuses.last.phase, BandPhase.failed);
      expect(statuses.last.message, contains('disconnected'));
    });

    test('leaving the screen stops the ring', () async {
      final ring = FakeRing(readings: const {});
      final band = everything(FakeCentral(ring));
      final sub = band.measure().listen((_) {});
      await Future<void>.delayed(const Duration(milliseconds: 15));
      await sub.cancel();
      await Future<void>.delayed(const Duration(milliseconds: 400));
      expect(ring.written.last[0], cmdStopMeasure);
      expect(ring.closed, isTrue);
    });
  });
}
