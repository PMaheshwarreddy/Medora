import 'package:web/web.dart' as web;

String? readTab(String name) {
  try {
    return web.window.sessionStorage.getItem(name);
  } catch (_) {
    // Storage can be blocked (private mode, kiosk policies).
    return null;
  }
}

void writeTab(String name, String? value) {
  try {
    if (value == null) {
      web.window.sessionStorage.removeItem(name);
    } else {
      web.window.sessionStorage.setItem(name, value);
    }
  } catch (_) {}
}
