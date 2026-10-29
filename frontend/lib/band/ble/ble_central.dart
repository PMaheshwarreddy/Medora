import 'dart:typed_data';

import 'ble_central_stub.dart'
    if (dart.library.js_interop) 'ble_central_web.dart'
    as platform;

/// Bluetooth Low Energy, as much of it as a band driver needs: find one
/// device, open one service, write to one characteristic and listen to
/// another. Shared by every band driver.
abstract class BleCentral {
  bool get isSupported;
  String get unsupportedReason;

  /// Connects to a device matching one of [filters]. Reuses the device
  /// chosen earlier when it can; otherwise opens the browser's chooser,
  /// which needs a user tap. Throws [BleException].
  Future<BleConnection> connect({
    required List<BleFilter> filters,
    required String service,
    required String writeCharacteristic,
    required String notifyCharacteristic,
  });
}

/// A device matches when it advertises [service], its name starts with
/// [namePrefix], or its manufacturer data for [company] starts with
/// [dataPrefix].
class BleFilter {
  const BleFilter.service(String this.service)
    : namePrefix = null,
      company = null,
      dataPrefix = const [];
  const BleFilter.namePrefix(String this.namePrefix)
    : service = null,
      company = null,
      dataPrefix = const [];
  const BleFilter.manufacturer(int this.company, this.dataPrefix)
    : service = null,
      namePrefix = null;

  final String? service;
  final String? namePrefix;
  final int? company;
  final List<int> dataPrefix;
}

abstract class BleConnection {
  String get deviceName;

  /// Packets the device sends.
  Stream<Uint8List> get notifications;

  /// Completes when the link drops, for whatever reason.
  Future<void> get disconnected;

  Future<void> write(Uint8List data);

  void close();
}

class BleException implements Exception {
  const BleException(this.message, {this.cancelled = false});

  /// For the patient.
  final String message;

  /// The patient closed the chooser without picking a device.
  final bool cancelled;

  @override
  String toString() => message;
}

BleCentral createBleCentral() => platform.createBleCentral();
