import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../kiosk/kiosk_key_store_stub.dart'
    if (dart.library.js_interop) '../kiosk/kiosk_key_store_web.dart';
import 'hospital_api.dart';

/// Who is signed in to one portal, if anyone. Each portal keeps its own
/// browser key, so a hospital admin, a doctor and the company back office
/// in the same browser never replace each other's sign-in.
class HospitalSessionController extends Notifier<HospitalApi?> {
  HospitalSessionController(this.storageKey);

  final String storageKey;

  String? readToken() => readStored(storageKey);

  @override
  HospitalApi? build() => null;

  void signIn(HospitalApi api) {
    writeStored(storageKey, api.token);
    state = api;
  }

  void update(HospitalApi api) => state = api;

  void signOut() {
    writeStored(storageKey, null);
    state = null;
  }
}

typedef PortalSession =
    NotifierProvider<HospitalSessionController, HospitalApi?>;

/// The hospital admin portal (`/hospital`).
final hospitalSessionProvider = PortalSession(
  () => HospitalSessionController('medora.hospitalSession'),
);

/// The doctor portal (`/doctor`).
final doctorSessionProvider = PortalSession(
  () => HospitalSessionController('medora.doctorSession'),
);
