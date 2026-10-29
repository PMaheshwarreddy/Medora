import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

import 'ble_central.dart';

/// Web Bluetooth: Chrome or Edge, on a secure origin (https or localhost).
/// On Linux Chrome hides it unless started with
/// `--enable-experimental-web-platform-features`, which `tool/chrome.sh`
/// adds; that switch also enables `getDevices`, used to reconnect to the
/// band chosen earlier without the chooser.
BleCentral createBleCentral() => _WebBluetooth();

// Where the chosen device is remembered between page loads, so a kiosk
// asks staff to pick the band once rather than once per patient.
const _rememberedKey = 'medora.bandDeviceId';

class _WebBluetooth implements BleCentral {
  _Device? _device;

  _Bluetooth? get _bluetooth => (web.window.navigator as JSObject)
      .getProperty<_Bluetooth?>('bluetooth'.toJS);

  @override
  bool get isSupported => _bluetooth != null && web.window.isSecureContext;

  @override
  String get unsupportedReason => !web.window.isSecureContext
      ? 'Bluetooth needs the kiosk to be opened over https.'
      : 'This browser cannot use Bluetooth. Open the kiosk in Google Chrome '
            '(on Linux, started with --enable-experimental-web-platform-features).';

  @override
  Future<BleConnection> connect({
    required List<BleFilter> filters,
    required String service,
    required String writeCharacteristic,
    required String notifyCharacteristic,
  }) async {
    final bluetooth = _bluetooth;
    if (bluetooth == null) throw BleException(unsupportedReason);

    final device =
        _device ??
        await _rememberedDevice(bluetooth) ??
        await _choose(bluetooth, filters, service);
    try {
      final link = await _open(
        device,
        service,
        writeCharacteristic,
        notifyCharacteristic,
      );
      _device = device;
      _remember(device.id);
      return link;
    } on BleException {
      // A remembered device that cannot be reached may be another one now;
      // the next attempt asks again.
      _device = null;
      _remember(null);
      rethrow;
    }
  }

  /// A device this site was allowed to use before, without the chooser.
  /// Chrome offers this only with its newer Bluetooth permissions.
  Future<_Device?> _rememberedDevice(_Bluetooth bluetooth) async {
    if (!bluetooth.has('getDevices')) return null;
    final id = _stored();
    if (id == null) return null;
    try {
      final devices = (await bluetooth.getDevices().toDart).toDart;
      for (final d in devices) {
        if (d.id == id) return d;
      }
    } catch (_) {}
    return null;
  }

  Future<_Device> _choose(
    _Bluetooth bluetooth,
    List<BleFilter> filters,
    String service,
  ) async {
    final options = JSObject()
      ..['filters'] = [for (final f in filters) _filter(f)].toJS
      ..['optionalServices'] = [service.toJS].toJS;
    try {
      return await bluetooth.requestDevice(options).toDart;
    } catch (e) {
      final text = e.toString();
      if (text.contains('NotFoundError') || text.contains('cancel')) {
        throw const BleException(
          'No device was chosen. If the list was empty, make sure the band '
          'is charged, close by, and not connected to a phone.',
          cancelled: true,
        );
      }
      if (text.contains('SecurityError')) {
        throw const BleException('Tap the button to connect.');
      }
      throw BleException('Bluetooth could not search for devices: $text');
    }
  }

  JSObject _filter(BleFilter f) {
    final filter = JSObject();
    if (f.service != null) filter['services'] = [f.service!.toJS].toJS;
    if (f.namePrefix != null) filter['namePrefix'] = f.namePrefix!.toJS;
    if (f.company != null) {
      // dataPrefix must be a BufferSource, so it is built by hand.
      filter['manufacturerData'] = [
        JSObject()
          ..['companyIdentifier'] = f.company!.toJS
          ..['dataPrefix'] = Uint8List.fromList(f.dataPrefix).toJS,
      ].toJS;
    }
    return filter;
  }

  Future<BleConnection> _open(
    _Device device,
    String service,
    String writeUuid,
    String notifyUuid,
  ) async {
    final gatt = device.gatt;
    if (gatt == null) throw const BleException('The device has no services.');
    try {
      final server = await gatt.connect().toDart.timeout(
        const Duration(seconds: 15),
      );
      final primary = await server.getPrimaryService(service.toJS).toDart;
      final write = await primary.getCharacteristic(writeUuid.toJS).toDart;
      final notify = await primary.getCharacteristic(notifyUuid.toJS).toDart;
      return await _WebConnection.open(device, gatt, write, notify);
    } on TimeoutException {
      gatt.disconnect();
      throw const BleException(
        'The device did not answer. Make sure it is charged and close by.',
      );
    } on BleException {
      rethrow;
    } catch (e) {
      gatt.disconnect();
      throw BleException('Could not connect to the device: $e');
    }
  }

  String? _stored() {
    try {
      return web.window.localStorage.getItem(_rememberedKey);
    } catch (_) {
      return null;
    }
  }

  void _remember(String? id) {
    try {
      if (id == null) {
        web.window.localStorage.removeItem(_rememberedKey);
      } else {
        web.window.localStorage.setItem(_rememberedKey, id);
      }
    } catch (_) {}
  }
}

class _WebConnection implements BleConnection {
  _WebConnection._(this._device, this._gatt, this._write, this._notify);

  static Future<_WebConnection> open(
    _Device device,
    _Server gatt,
    _Characteristic write,
    _Characteristic notify,
  ) async {
    final link = _WebConnection._(device, gatt, write, notify);
    device.addEventListener('gattserverdisconnected', link._onDrop);
    notify.addEventListener('characteristicvaluechanged', link._onValue);
    await notify.startNotifications().toDart;
    return link;
  }

  final _Device _device;
  final _Server _gatt;
  final _Characteristic _write;
  final _Characteristic _notify;
  final _packets = StreamController<Uint8List>.broadcast();
  final _dropped = Completer<void>();
  // Web Bluetooth refuses a write while another is still in flight.
  Future<void> _lastWrite = Future.value();

  late final JSFunction _onDrop = ((web.Event _) => _drop()).toJS;
  late final JSFunction _onValue = ((web.Event _) {
    final view = _notify.value;
    if (view == null) return;
    final data = view.toDart;
    _packets.add(
      Uint8List.fromList(
        data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
      ),
    );
  }).toJS;

  @override
  String get deviceName => _device.name ?? 'Band';

  @override
  Stream<Uint8List> get notifications => _packets.stream;

  @override
  Future<void> get disconnected => _dropped.future;

  @override
  Future<void> write(Uint8List data) {
    final next = _lastWrite.then((_) async {
      if (_dropped.isCompleted) {
        throw const BleException('The device disconnected.');
      }
      final props = _write.properties;
      if (props.write) {
        await _write.writeValueWithResponse(data.toJS).toDart;
      } else {
        await _write.writeValueWithoutResponse(data.toJS).toDart;
      }
    });
    _lastWrite = next.catchError((_) {});
    return next;
  }

  void _drop() {
    if (_dropped.isCompleted) return;
    _device.removeEventListener('gattserverdisconnected', _onDrop);
    _notify.removeEventListener('characteristicvaluechanged', _onValue);
    _dropped.complete();
    _packets.close();
  }

  @override
  void close() {
    if (_gatt.connected) _gatt.disconnect();
    _drop();
  }
}

// --- Web Bluetooth, the parts used here ----------------------------------

extension type _Bluetooth._(JSObject _) implements JSObject {
  external JSPromise<_Device> requestDevice(JSObject options);
  external JSPromise<JSArray<_Device>> getDevices();
}

extension type _Device._(JSObject _) implements web.EventTarget {
  external String get id;
  external String? get name;
  external _Server? get gatt;
}

extension type _Server._(JSObject _) implements JSObject {
  external bool get connected;
  external JSPromise<_Server> connect();
  external void disconnect();
  external JSPromise<_Service> getPrimaryService(JSString uuid);
}

extension type _Service._(JSObject _) implements JSObject {
  external JSPromise<_Characteristic> getCharacteristic(JSString uuid);
}

extension type _Characteristic._(JSObject _) implements web.EventTarget {
  external _Properties get properties;
  external JSDataView? get value;
  external JSPromise<JSAny?> startNotifications();
  external JSPromise<JSAny?> writeValueWithResponse(JSUint8Array value);
  external JSPromise<JSAny?> writeValueWithoutResponse(JSUint8Array value);
}

extension type _Properties._(JSObject _) implements JSObject {
  external bool get write;
}
