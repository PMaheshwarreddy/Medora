import 'dart:async';

import '../../../models/intake.dart';
import '../../band_service.dart';
import '../../ble/ble_central.dart';
import 'qring_protocol.dart';

/// How long each step may take. The defaults follow the vendor SDK: it
/// waits 30 s for each manual measurement and keeps the last reading.
class QRingTiming {
  const QRingTiming({
    this.settle = const Duration(milliseconds: 600),
    this.reply = const Duration(milliseconds: 2500),
    this.window = const Duration(seconds: 30),
    this.gap = const Duration(milliseconds: 400),
  });

  /// After notifications are on, before the first command: the SDK warns
  /// that commands sent at once are often lost.
  final Duration settle;

  /// For the time-sync reply; tried three times.
  final Duration reply;

  /// For one measurement.
  final Duration window;

  /// Between measurements; the ring takes one command at a time.
  final Duration gap;
}

/// A QC Wireless (QRing SDK) smart band, over Web Bluetooth.
class QRingBand implements BandService {
  QRingBand(
    this._ble, {
    this.timing = const QRingTiming(),
    this.measures = const [VitalSign.heartRate, VitalSign.spo2],
  });

  final BleCentral _ble;
  final QRingTiming timing;

  /// The Y26 band in use has heart-rate and SpO2 sensors only. A QC Wireless
  /// model with blood pressure or temperature can list those too; the
  /// band's capability reply still decides what is actually measured.
  @override
  final List<VitalSign> measures;

  @override
  String get deviceNoun => 'band';

  @override
  String get wearInstruction =>
      'Wear the band snugly on your wrist, just above the wrist bone, with '
      'the sensor touching your skin. Rest your arm on the table and keep '
      'still until every reading is done.';

  @override
  bool get isAvailable => _ble.isSupported;

  @override
  String get unavailableReason => _ble.unsupportedReason;

  @override
  Stream<BandStatus> measure() {
    late final _Run run;
    final out = StreamController<BandStatus>(onCancel: () => run.cancel());
    run = _Run(_ble, out, timing, measures)..start();
    return out.stream;
  }
}

/// Order the vitals are taken in, and the ring's type for each.
const _types = {
  VitalSign.heartRate: typeHeartRate,
  VitalSign.spo2: typeSpo2,
  VitalSign.bloodPressure: typeBloodPressure,
  VitalSign.temperature: typeBodyTemperature,
};

/// One connect-measure-disconnect cycle.
class _Run {
  _Run(this._ble, this._out, this._timing, this._wanted);

  final BleCentral _ble;
  final List<VitalSign> _wanted;
  final StreamController<BandStatus> _out;
  final QRingTiming _timing;
  final _packets = StreamController<RingPacket>.broadcast();

  BleConnection? _link;
  StreamSubscription<void>? _incoming;
  bool _over = false;
  bool _dropped = false;
  int? _measuring;

  Vitals _vitals = const Vitals();
  Set<VitalSign> _supported = const {};
  final _missed = <VitalSign>{};

  Future<void> start() async {
    _emit(BandPhase.connecting);
    final BleConnection link;
    try {
      link = await _ble.connect(
        filters: const [
          BleFilter.manufacturer(advertisedCompany, advertisedDataPrefix),
          BleFilter.service(advertisedService),
          // Not what the SDK scans for, but harmless and a second chance
          // for a ring that advertises its data service.
          BleFilter.service(serviceUuid),
        ],
        service: serviceUuid,
        writeCharacteristic: writeUuid,
        notifyCharacteristic: notifyUuid,
      );
    } on BleException catch (e) {
      _finish(BandPhase.failed, e.message);
      return;
    }
    if (_over) {
      link.close();
      return;
    }
    _link = link;
    _incoming = link.notifications.listen((bytes) {
      final packet = RingPacket.parse(bytes);
      if (packet != null) _packets.add(packet);
    });
    unawaited(
      link.disconnected.then((_) {
        _dropped = true;
        _finish(
          BandPhase.failed,
          'The band disconnected. Keep it close to the kiosk and try again.',
        );
      }),
    );

    try {
      _emit(BandPhase.preparing);
      await Future<void>.delayed(_timing.settle);
      final can = await _capabilities(link);
      final hardware = {
        VitalSign.heartRate,
        if (can.spo2) VitalSign.spo2,
        if (can.bloodPressure) VitalSign.bloodPressure,
        if (can.temperature) VitalSign.temperature,
      };
      _supported = {
        for (final s in _wanted)
          if (hardware.contains(s)) s,
      };
      for (final sign in _types.keys) {
        if (_over) return;
        if (!_supported.contains(sign)) continue;
        await _measure(link, sign);
        await Future<void>.delayed(_timing.gap);
      }
      _finish(BandPhase.done);
    } on BleException catch (e) {
      _finish(BandPhase.failed, e.message);
    }
  }

  Future<RingCapabilities> _capabilities(BleConnection link) async {
    for (var attempt = 0; attempt < 3 && !_over; attempt++) {
      final reply = _packets.stream
          .firstWhere((p) => p.command == cmdSetTime && !p.refused)
          .timeout(_timing.reply);
      await link.write(setTime(DateTime.now()));
      try {
        return RingCapabilities.from(await reply);
      } on TimeoutException {
        // The ring is slow to wake; ask again.
      } on StateError {
        break; // the link closed
      }
    }
    throw const BleException(
      'The band did not respond. Take it off the charger, wait a few '
      'seconds and try again.',
    );
  }

  /// One vital. Keeps the last plausible reading the ring sends in the
  /// window; heart rate is done at its first one, as in the SDK.
  Future<void> _measure(BleConnection link, VitalSign sign) async {
    final type = _types[sign]!;
    _measuring = type;
    _emit(BandPhase.measuring, current: sign);

    final done = Completer<void>();
    var refused = false;
    final readings = _packets.stream
        .where((p) => p.command == cmdStartMeasure)
        .listen((p) {
          final r = MeasureReading.from(p);
          if (r.type != type || done.isCompleted) return;
          if (p.refused || r.error != 0) {
            refused = true;
            done.complete();
            return;
          }
          if (_take(sign, r)) {
            _emit(BandPhase.measuring, current: sign);
            if (sign == VitalSign.heartRate) done.complete();
          }
        });
    final timer = Timer(_timing.window, () {
      if (!done.isCompleted) done.complete();
    });
    unawaited(
      link.disconnected.then((_) {
        if (!done.isCompleted) done.complete();
      }),
    );

    await link.write(startMeasure(type));
    await done.future;
    timer.cancel();
    unawaited(readings.cancel());
    _measuring = null;
    if (_dropped || _over) return;

    // The ring keeps the values it is stopped with as its own record.
    final (first, second) = switch (sign) {
      VitalSign.heartRate => (_vitals.heartRate ?? 0, 0),
      VitalSign.spo2 => (_vitals.spo2 ?? 0, 0),
      VitalSign.bloodPressure => (
        _vitals.systolic ?? 0,
        _vitals.diastolic ?? 0,
      ),
      VitalSign.temperature => (0, 0),
    };
    await link.write(stopMeasure(type, first, second));
    if (refused || !_has(sign)) _missed.add(sign);
  }

  /// Stores a reading if it is physiologically possible; a ring that slips
  /// produces nonsense, and nonsense must not reach a triage report.
  bool _take(VitalSign sign, MeasureReading r) {
    switch (sign) {
      case VitalSign.heartRate:
        if (r.value < 30 || r.value > 220) return false;
        _vitals = _vitals.copyWith(heartRate: r.value);
      case VitalSign.spo2:
        if (r.value < 70 || r.value > 100) return false;
        _vitals = _vitals.copyWith(spo2: r.value);
      case VitalSign.bloodPressure:
        final ok =
            r.systolic >= 70 &&
            r.systolic <= 250 &&
            r.diastolic >= 40 &&
            r.diastolic <= 150 &&
            r.systolic > r.diastolic;
        if (!ok) return false;
        _vitals = _vitals.copyWith(
          systolic: r.systolic,
          diastolic: r.diastolic,
        );
      case VitalSign.temperature:
        final t = r.temperatureC;
        if (r.value == 0 || t < 34 || t > 42.5) return false;
        _vitals = _vitals.copyWith(temperatureC: t);
    }
    return true;
  }

  bool _has(VitalSign sign) => switch (sign) {
    VitalSign.heartRate => _vitals.heartRate != null,
    VitalSign.spo2 => _vitals.spo2 != null,
    VitalSign.bloodPressure => _vitals.systolic != null,
    VitalSign.temperature => _vitals.temperatureC != null,
  };

  void _emit(BandPhase phase, {VitalSign? current, String? message}) {
    if (_out.isClosed) return;
    _out.add(
      BandStatus(
        phase,
        vitals: _vitals,
        supported: _supported,
        current: current,
        window: current == null ? null : _timing.window,
        missed: {..._missed},
        deviceName: _link?.deviceName,
        message: message,
      ),
    );
  }

  void _finish(BandPhase phase, [String? message]) {
    if (_over) return;
    if (phase == BandPhase.done && _missed.length == _supported.length) {
      phase = BandPhase.failed;
      message =
          'The band could not take a reading. Tighten it so the sensor '
          'touches the skin, and try again.';
    }
    _emit(phase, message: message);
    _over = true;
    _shutdown();
    _out.close();
  }

  /// The patient left the screen: stop the ring and let it go.
  void cancel() {
    if (_over) return;
    _over = true;
    _shutdown();
  }

  void _shutdown() {
    final link = _link;
    final type = _measuring;
    _incoming?.cancel();
    _packets.close();
    if (link == null) return;
    if (type != null && !_dropped) {
      // Stop the ring mid-measurement, and give that command a moment to
      // leave before the link closes.
      link.write(stopMeasure(type)).catchError((_) {});
      Future<void>.delayed(const Duration(milliseconds: 300), link.close);
    } else {
      link.close();
    }
  }
}
