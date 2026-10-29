import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/intake.dart';

class IntakeController extends Notifier<IntakeSession> {
  @override
  IntakeSession build() => const IntakeSession();

  void start(IntakeMode mode) => state = IntakeSession(mode: mode);

  void setPatient(PatientIntake patient) =>
      state = state.copyWith(patient: patient);

  /// Fields heard by the voice agent; only the ones present are changed.
  void mergePatient(Map<String, dynamic> fields) =>
      state = state.copyWith(patient: state.patient.merge(fields));

  void setVitals(Vitals vitals) => state = state.copyWith(vitals: vitals);

  void setSessionId(String id) => state = state.copyWith(sessionId: id);

  /// The details came from the patient's phone through hand-off [code].
  void fromPhone(String code, PatientIntake patient) => state = IntakeSession(
    mode: IntakeMode.phone,
    patient: patient,
    handoffCode: code,
  );

  /// The complaint does not call for vitals; [reason] is for the patient.
  void skipVitals(String reason) =>
      state = state.copyWith(vitalsNotNeeded: reason);

  /// Vitals are wanted after all (the patient changed their complaint).
  void wantVitals() => state = IntakeSession(
    mode: state.mode,
    patient: state.patient,
    vitals: state.vitals,
    sessionId: state.sessionId,
    handoffCode: state.handoffCode,
  );

  void reset() => state = const IntakeSession();
}

final intakeProvider = NotifierProvider<IntakeController, IntakeSession>(
  IntakeController.new,
);
