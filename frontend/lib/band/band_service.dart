import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/intake.dart';
import 'band_registry.dart';

/// What a band can measure.
enum VitalSign {
  heartRate('Heart rate'),
  spo2('Oxygen level'),
  bloodPressure('Blood pressure'),
  temperature('Temperature');

  const VitalSign(this.label);

  final String label;
}

enum BandPhase {
  /// Finding the band and opening the Bluetooth link.
  connecting,

  /// Linked; asking the band what it can measure.
  preparing,

  /// Taking readings one vital at a time.
  measuring,

  /// Finished. [BandStatus.vitals] holds every reading the band gave.
  done,

  /// Stopped before finishing; [BandStatus.message] says why.
  failed,
}

/// Where a measurement is, for the screen to show.
class BandStatus {
  const BandStatus(
    this.phase, {
    this.vitals = const Vitals(),
    this.supported = const {},
    this.current,
    this.window,
    this.missed = const {},
    this.deviceName,
    this.message,
  });

  final BandPhase phase;

  /// Readings so far.
  final Vitals vitals;

  /// What this band can measure; empty until it has said so.
  final Set<VitalSign> supported;

  /// The vital being measured now, and how long that measurement may take.
  final VitalSign? current;
  final Duration? window;

  /// Supported vitals the band tried but could not read.
  final Set<VitalSign> missed;

  final String? deviceName;

  /// For the patient, when something went wrong.
  final String? message;
}

/// A smart band the kiosk takes vitals with.
///
/// Every band is a driver under `band/drivers/<name>/` implementing this
/// interface; `band_registry.dart` picks the one this kiosk uses. Screens and
/// the voice agent only ever talk to this interface.
abstract class BandService {
  /// How the patient knows the device: "ring", "band", "watch".
  String get deviceNoun;

  /// What the patient should do before tapping start.
  String get wearInstruction;

  /// The vitals this band can take, in the order it takes them. Screens
  /// show only these; the band's own answer after connecting can narrow it.
  List<VitalSign> get measures;

  /// False when this kiosk cannot reach the band at all (for example a
  /// browser without Bluetooth); [unavailableReason] says why.
  bool get isAvailable;
  String get unavailableReason;

  /// Connects and measures every vital the band supports, then disconnects.
  ///
  /// Call it straight from a tap: browsers open the Bluetooth chooser only
  /// in response to one. Cancelling the subscription stops the band.
  Stream<BandStatus> measure();
}

class BandNotIntegrated implements BandService {
  const BandNotIntegrated();

  @override
  String get deviceNoun => 'band';

  @override
  String get wearInstruction => '';

  @override
  List<VitalSign> get measures => const [];

  @override
  bool get isAvailable => false;

  @override
  String get unavailableReason => 'No band is set up on this kiosk.';

  @override
  Stream<BandStatus> measure() => const Stream.empty();
}

/// The band the screens and the voice agent use: whichever
/// `band_registry.dart` picks.
final bandServiceProvider = Provider<BandService>(createBand);
