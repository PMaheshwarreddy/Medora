import 'package:web/web.dart' as web;

String? readStored(String name) {
  try {
    return web.window.localStorage.getItem(name);
  } catch (_) {
    // Storage can be blocked (private mode, kiosk policies).
    return null;
  }
}

void writeStored(String name, String? value) {
  try {
    if (value == null) {
      web.window.localStorage.removeItem(name);
    } else {
      web.window.localStorage.setItem(name, value);
    }
  } catch (_) {}
}
