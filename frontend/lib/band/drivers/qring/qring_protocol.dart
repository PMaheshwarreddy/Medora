/// The QRing (QC Wireless) Bluetooth protocol, as used by the vendor's
/// Android SDK 1.0.0.57 in `SDK/QRing_Android_SDK_1.0.0.57`. The values
/// here were read from that SDK (classes `Constants`, `BaseReqCmd`,
/// `SetTimeReq`/`SetTimeRsp`, `StartHeartRateReq`/`Rsp`, `StopHeartRateReq`
/// and `BleOperateManager.manualMode*`); the class each comes from is named
/// beside it so it can be checked against a newer SDK.
///
/// Every packet is 16 bytes: a command byte, up to 14 bytes of data, and a
/// checksum (the low byte of the sum of the first 15). Replies use the same
/// command byte; bit 0x80 set means the ring refused the command.
library;

import 'dart:typed_data';

/// `Constants.UUID_SERVICE`, `UUID_WRITE`, `UUID_READ`.
const serviceUuid = '6e40fff0-b5a3-f393-e0a9-e50e24dcca9e';
const writeUuid = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
const notifyUuid = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

/// What `BleScannerHelper.scanDevice` filters on: rings advertise this
/// service. (The SDK's name-prefix lists are for clearing paired watches,
/// not for finding rings.)
const advertisedService = '0000fee7-0000-1000-8000-00805f9b34fb';

/// What the bands actually advertise (seen on a Y26 band): manufacturer
/// data under company 0x1234 that starts with fe e7, then the band's
/// address. Android matches that against the fee7 filter; Chrome does not.
const advertisedCompany = 0x1234;
const advertisedDataPrefix = [0xFE, 0xE7];

const packetLength = 16;
const _errorFlag = 0x80;

/// `Constants.CMD_SET_DEVICE_TIME`, `CMD_START_HEART_RATE`,
/// `CMD_STOP_HEART_RATE` (the start/stop pair serves every manual
/// measurement, not only heart rate).
const cmdSetTime = 0x01;
const cmdStartMeasure = 0x69;
const cmdStopMeasure = 0x6A;

/// `StartHeartRateReq.TYPE_*`.
const typeHeartRate = 1;
const typeBloodPressure = 2;
const typeSpo2 = 3;
const typeBodyTemperature = 11;

/// One packet with its checksum.
Uint8List packet(int command, [List<int> data = const []]) {
  assert(data.length <= packetLength - 2);
  final bytes = Uint8List(packetLength);
  bytes[0] = command;
  bytes.setAll(1, data);
  bytes[packetLength - 1] = _sum(bytes);
  return bytes;
}

int _sum(Uint8List bytes) {
  var sum = 0;
  for (var i = 0; i < packetLength - 1; i++) {
    sum += bytes[i];
  }
  return sum & 0xFF;
}

int _bcd(int value) => ((value ~/ 10) << 4) | (value % 10);

/// `SetTimeReq`: the ring must be told the time before it will measure, and
/// its reply says what it can measure. The last byte is the language; 1 is
/// anything other than Chinese.
Uint8List setTime(DateTime now) => packet(cmdSetTime, [
  _bcd(now.year - 2000),
  _bcd(now.month),
  _bcd(now.day),
  _bcd(now.hour),
  _bcd(now.minute),
  _bcd(now.second),
  1,
]);

/// `StartHeartRateReq.getSimpleReq(type)`: types from blood oxygen up carry
/// 25 (in BCD) as their second byte.
Uint8List startMeasure(int type) =>
    packet(cmdStartMeasure, [type, type < typeSpo2 ? 0 : _bcd(25), 0]);

/// `StopHeartRateReq.stop*`: the type and the last value read, which the
/// ring keeps as the result.
Uint8List stopMeasure(int type, [int first = 0, int second = 0]) =>
    packet(cmdStopMeasure, [type, first & 0xFF, second & 0xFF]);

/// A packet the ring sent, or null when it is not a whole, intact packet.
class RingPacket {
  RingPacket._(this.bytes);

  static RingPacket? parse(Uint8List bytes) {
    if (bytes.length != packetLength) return null;
    if (bytes[packetLength - 1] != _sum(bytes)) return null;
    return RingPacket._(bytes);
  }

  final Uint8List bytes;

  int get command => bytes[0] & ~_errorFlag;
  bool get refused => bytes[0] & _errorFlag != 0;

  /// The data bytes, as the SDK's `acceptData` sees them.
  int operator [](int i) => bytes[i + 1];
}

/// `SetTimeRsp.acceptData`: which measurements the ring has hardware for.
class RingCapabilities {
  const RingCapabilities({
    required this.temperature,
    required this.spo2,
    required this.bloodPressure,
  });

  factory RingCapabilities.from(RingPacket reply) => RingCapabilities(
    temperature: reply[0] == 1,
    spo2: reply[3] & 0x02 != 0,
    bloodPressure: reply[3] & 0x04 != 0,
  );

  final bool temperature;
  final bool spo2;
  final bool bloodPressure;
}

/// `StartHeartRateRsp.acceptData`, for the measurement types used here.
class MeasureReading {
  MeasureReading.from(RingPacket p)
    : type = p[0],
      error = p[1],
      value = p[2],
      systolic = p[3],
      diastolic = p[4];

  final int type;

  /// 0 while all is well; anything else means the ring gave up (most often
  /// because it is not worn, or worn too loosely).
  final int error;

  /// Heart rate (bpm) or SpO2 (%); for temperature, tenths of a degree
  /// above 20 °C (`BleOperateManager` adds 200).
  final int value;
  final int systolic;
  final int diastolic;

  double get temperatureC => (value + 200) / 10;
}
