import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'band_service.dart';
// Real band (QC Wireless Y26): uncomment these two imports with its line below.
// import 'ble/ble_central.dart';
// import 'drivers/qring/qring_band.dart';
// Band simulator: comment this import out with its line below.
import 'drivers/simulator/simulator_band.dart';

/// The one place that decides which band this kiosk uses.
///
/// NOW: the simulator. Heart rate, SpO2, temperature and blood pressure come
/// from sliders on the vitals screen (drivers/simulator/), and everything
/// after that (report, PDF, voice agent) works exactly as with a real band.
///
/// TO GO BACK TO THE REAL BAND: uncomment the two real-band imports above
/// and the QRingBand line below; comment out the simulator import and the
/// SimulatorBand line. Nothing else needs to change: the sliders only appear
/// while the simulator is the band.
///
/// To add another band: add a driver folder under `drivers/` that
/// implements [BandService] and return it here.
BandService createBand(Ref ref) =>
    // QRingBand(createBleCentral());
    SimulatorBand(() => ref.read(simulatorProvider));
