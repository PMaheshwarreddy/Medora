import 'kiosk_key_store_stub.dart'
    if (dart.library.js_interop) 'kiosk_key_store_web.dart';

const _kioskKey = 'medora.kioskKey';
const _session = 'medora.session';

/// Remembers this kiosk's key across reloads.
///
/// A kiosk is set up by opening its link once (`/#/kiosk?key=mk_...`). The
/// key is then kept in the browser, so the kiosk keeps belonging to its
/// client when the page reloads on another screen of the flow.
String? readKioskKey() => readStored(_kioskKey);

void saveKioskKey(String key) => writeStored(_kioskKey, key);

/// The back-office sign-in, kept so a reload does not sign the user out.
/// Null value clears it.
String? readSessionToken() => readStored(_session);

void saveSessionToken(String? token) => writeStored(_session, token);
