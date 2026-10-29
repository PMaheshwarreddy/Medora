import 'ble_central.dart';

/// Outside a browser (tests, desktop builds) there is no Bluetooth.
BleCentral createBleCentral() => const _NoBluetooth();

class _NoBluetooth implements BleCentral {
  const _NoBluetooth();

  @override
  bool get isSupported => false;

  @override
  String get unsupportedReason => 'Bluetooth is not available here.';

  @override
  Future<BleConnection> connect({
    required List<BleFilter> filters,
    required String service,
    required String writeCharacteristic,
    required String notifyCharacteristic,
  }) => throw const BleException('Bluetooth is not available here.');
}
