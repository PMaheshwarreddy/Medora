import 'dart:convert';

import '../models/intake.dart';
import 'visit_store_stub.dart'
    if (dart.library.js_interop) 'visit_store_web.dart';

const _visit = 'medora.visit';
const _language = 'medora.visitLanguage';

/// Keeps the visit in progress (details, vitals, saved visit id) across a
/// page reload, so a refresh mid-visit does not lose what the patient has
/// already given (the user's report of 2026-10-29: "refreshed, all went
/// blank"). Held in the tab's session storage: gone when the tab closes,
/// and cleared when the visit ends.
IntakeSession? readVisit() {
  final raw = readTab(_visit);
  if (raw == null || raw.isEmpty) return null;
  try {
    final visit = IntakeSession.fromJson(
      (jsonDecode(raw) as Map).cast<String, dynamic>(),
    );
    return visit.mode == null ? null : visit;
  } catch (_) {
    return null;
  }
}

void saveVisit(IntakeSession visit) =>
    writeTab(_visit, visit.mode == null ? null : jsonEncode(visit.toJson()));

/// The visit's language ('en' or 'ml'), kept the same way.
String? readVisitLanguage() => readTab(_language);

void saveVisitLanguage(String? code) => writeTab(_language, code);
