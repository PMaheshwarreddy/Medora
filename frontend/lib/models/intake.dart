/// phone: filled in on the patient's own phone (QR at the kiosk).
enum IntakeMode { voice, manual, phone }

enum Gender { male, female, other }

class PatientIntake {
  const PatientIntake({
    this.name = '',
    this.age,
    this.gender,
    this.phone = '',
    this.email = '',
    this.symptoms = '',
    this.duration = '',
    this.medications = '',
    this.allergies = '',
    this.pregnancy = '',
    this.conditions = '',
    this.regularMedicines = '',
    this.surgeries = '',
    this.habits = '',
    this.weightKg,
    this.patientId,
  });

  final String name;
  final int? age;
  final Gender? gender;
  final String phone;
  final String email;
  final String symptoms;
  final String duration;
  final String medications;
  final String allergies;

  /// yes, no or unsure, only when the voice agent asked (a complaint where
  /// pregnancy matters); empty otherwise.
  final String pregnancy;

  /// Health history: long-term conditions, daily medicines, past operations.
  final String conditions;
  final String regularMedicines;
  final String surgeries;

  /// Smoking, tobacco and alcohol, as said (the voice agent asks adult men).
  final String habits;
  final double? weightKg;

  /// A returning patient picked under their phone number; null for new.
  final String? patientId;

  PatientIntake copyWith({
    String? name,
    int? age,
    Gender? gender,
    String? phone,
    String? email,
    String? symptoms,
    String? duration,
    String? medications,
    String? allergies,
    String? pregnancy,
    String? conditions,
    String? regularMedicines,
    String? surgeries,
    String? habits,
    double? weightKg,
    String? patientId,
    bool clearPatient = false,
  }) => PatientIntake(
    name: name ?? this.name,
    age: age ?? this.age,
    gender: gender ?? this.gender,
    phone: phone ?? this.phone,
    email: email ?? this.email,
    symptoms: symptoms ?? this.symptoms,
    duration: duration ?? this.duration,
    medications: medications ?? this.medications,
    allergies: allergies ?? this.allergies,
    pregnancy: pregnancy ?? this.pregnancy,
    conditions: conditions ?? this.conditions,
    regularMedicines: regularMedicines ?? this.regularMedicines,
    surgeries: surgeries ?? this.surgeries,
    habits: habits ?? this.habits,
    weightKg: weightKg ?? this.weightKg,
    patientId: clearPatient ? null : (patientId ?? this.patientId),
  );

  /// As the API takes it (also what the phone sends to the kiosk).
  Map<String, dynamic> toJson() => {
    'name': name,
    'age': age,
    'gender': gender?.name,
    'phone': phone,
    'email': email,
    'symptoms': symptoms,
    'duration': duration,
    'medications': medications,
    'allergies': allergies,
    'pregnancy': pregnancy,
    'chronicConditions': conditions,
    'regularMedicines': regularMedicines,
    'pastSurgeries': surgeries,
    'habits': habits,
    'weightKg': weightKg,
    'patientId': patientId,
  };

  /// What a phone sent (the hand-off) or the API stored.
  factory PatientIntake.fromJson(Map<String, dynamic> j) => PatientIntake(
    name: j['name'] as String? ?? '',
    age: j['age'] as int?,
    gender: Gender.values.asNameMap()[j['gender']],
    phone: j['phone'] as String? ?? '',
    email: j['email'] as String? ?? '',
    symptoms: j['symptoms'] as String? ?? '',
    duration: j['duration'] as String? ?? '',
    medications: j['medications'] as String? ?? '',
    allergies: j['allergies'] as String? ?? '',
    pregnancy: j['pregnancy'] as String? ?? '',
    conditions: j['chronicConditions'] as String? ?? '',
    regularMedicines: j['regularMedicines'] as String? ?? '',
    surgeries: j['pastSurgeries'] as String? ?? '',
    habits: j['habits'] as String? ?? '',
    weightKg: (j['weightKg'] as num?)?.toDouble(),
    patientId: j['patientId'] as String?,
  );

  /// Applies the fields the voice agent heard, as sent by the server.
  PatientIntake merge(Map<String, dynamic> fields) => copyWith(
    name: fields['name'] as String?,
    age: fields['age'] as int?,
    gender: Gender.values.asNameMap()[fields['gender']],
    phone: fields['phone'] as String?,
    email: fields['email'] as String?,
    symptoms: fields['symptoms'] as String?,
    duration: fields['duration'] as String?,
    medications: fields['medications'] as String?,
    allergies: fields['allergies'] as String?,
    pregnancy: fields['pregnancy'] as String?,
    conditions: fields['chronic_conditions'] as String?,
    regularMedicines: fields['regular_medicines'] as String?,
    habits: fields['habits'] as String?,
    weightKg: (fields['weight_kg'] as num?)?.toDouble(),
  );

  /// What is known so far, as the voice agent names the fields (the
  /// conversation restarted, e.g. after a reload, carries on from these).
  Map<String, dynamic> toVoiceFields() => {
    if (name.isNotEmpty) 'name': name,
    'age': ?age,
    if (gender != null) 'gender': gender!.name,
    if (phone.isNotEmpty) 'phone': phone,
    if (email.isNotEmpty) 'email': email,
    if (symptoms.isNotEmpty) 'symptoms': symptoms,
    if (duration.isNotEmpty) 'duration': duration,
    if (medications.isNotEmpty) 'medications': medications,
    if (allergies.isNotEmpty) 'allergies': allergies,
    if (pregnancy.isNotEmpty) 'pregnancy': pregnancy,
    if (conditions.isNotEmpty) 'chronic_conditions': conditions,
    if (regularMedicines.isNotEmpty) 'regular_medicines': regularMedicines,
    if (habits.isNotEmpty) 'habits': habits,
    'weight_kg': ?weightKg,
  };

  /// Everything the triage step needs before it can run.
  bool get isComplete =>
      name.trim().isNotEmpty &&
      age != null &&
      gender != null &&
      phone.trim().isNotEmpty &&
      symptoms.trim().isNotEmpty;
}

/// Readings from the band. There is no manual entry: a null field means the
/// band has not reported that value yet.
class Vitals {
  const Vitals({
    this.heartRate,
    this.spo2,
    this.temperatureC,
    this.systolic,
    this.diastolic,
  });

  final int? heartRate;
  final int? spo2;
  final double? temperatureC;
  final int? systolic;
  final int? diastolic;

  /// True when the band has given at least one reading. A band measures
  /// only what its hardware supports, so a complete set is not required.
  bool get hasAny =>
      heartRate != null ||
      spo2 != null ||
      temperatureC != null ||
      systolic != null;

  Map<String, dynamic> toJson() => {
    'heartRate': heartRate,
    'spo2': spo2,
    'temperatureC': temperatureC,
    'systolic': systolic,
    'diastolic': diastolic,
  };

  factory Vitals.fromJson(Map<String, dynamic> j) => Vitals(
    heartRate: (j['heartRate'] as num?)?.toInt(),
    spo2: (j['spo2'] as num?)?.toInt(),
    temperatureC: (j['temperatureC'] as num?)?.toDouble(),
    systolic: (j['systolic'] as num?)?.toInt(),
    diastolic: (j['diastolic'] as num?)?.toInt(),
  );

  Vitals copyWith({
    int? heartRate,
    int? spo2,
    double? temperatureC,
    int? systolic,
    int? diastolic,
  }) => Vitals(
    heartRate: heartRate ?? this.heartRate,
    spo2: spo2 ?? this.spo2,
    temperatureC: temperatureC ?? this.temperatureC,
    systolic: systolic ?? this.systolic,
    diastolic: diastolic ?? this.diastolic,
  );
}

class IntakeSession {
  const IntakeSession({
    this.mode,
    this.patient = const PatientIntake(),
    this.vitals = const Vitals(),
    this.sessionId,
    this.vitalsNotNeeded,
    this.handoffCode,
  });

  /// Set once the server has stored the confirmed intake.
  final String? sessionId;
  final IntakeMode? mode;
  final PatientIntake patient;
  final Vitals vitals;

  /// Set when the complaint did not call for vitals, with why (may be
  /// empty); null when vitals were wanted.
  final String? vitalsNotNeeded;

  /// Set when the details came from the patient's phone (the QR code).
  final String? handoffCode;

  IntakeSession copyWith({
    IntakeMode? mode,
    PatientIntake? patient,
    Vitals? vitals,
    String? sessionId,
    String? vitalsNotNeeded,
    String? handoffCode,
  }) => IntakeSession(
    sessionId: sessionId ?? this.sessionId,
    mode: mode ?? this.mode,
    patient: patient ?? this.patient,
    vitals: vitals ?? this.vitals,
    vitalsNotNeeded: vitalsNotNeeded ?? this.vitalsNotNeeded,
    handoffCode: handoffCode ?? this.handoffCode,
  );

  /// For keeping the visit across a page reload (state/visit_store.dart).
  Map<String, dynamic> toJson() => {
    'mode': mode?.name,
    'patient': patient.toJson(),
    'vitals': vitals.toJson(),
    'sessionId': sessionId,
    'vitalsNotNeeded': vitalsNotNeeded,
    'handoffCode': handoffCode,
  };

  factory IntakeSession.fromJson(Map<String, dynamic> j) => IntakeSession(
    mode: IntakeMode.values.asNameMap()[j['mode']],
    patient: PatientIntake.fromJson(
      (j['patient'] as Map?)?.cast<String, dynamic>() ?? const {},
    ),
    vitals: Vitals.fromJson(
      (j['vitals'] as Map?)?.cast<String, dynamic>() ?? const {},
    ),
    sessionId: j['sessionId'] as String?,
    vitalsNotNeeded: j['vitalsNotNeeded'] as String?,
    handoffCode: j['handoffCode'] as String?,
  );
}

enum Urgency { routine, soon, urgent, emergency }

class PossibleCondition {
  PossibleCondition.fromJson(Map<String, dynamic> j)
    : name = j['name'] as String,
      likelihood = j['likelihood'] as String,
      reasoning = j['reasoning'] as String? ?? '',
      raisedBy = j['raisedBy'] as String? ?? '';

  final String name;

  /// `high`, `medium` or `low`.
  final String likelihood;
  final String reasoning;

  /// The specialists who argued for it.
  final String raisedBy;
}

class SpecialistOpinion {
  SpecialistOpinion.fromJson(Map<String, dynamic> j)
    : specialist = j['specialist'] as String,
      relevant = j['relevant'] as bool? ?? true,
      assessment = j['assessment'] as String? ?? '';

  final String specialist;

  /// False when the specialist judged the case to be outside their field.
  final bool relevant;
  final String assessment;
}

/// A medicine the report suggests for the doctor to confirm.
class Medicine {
  Medicine.fromJson(Map<String, dynamic> j)
    : name = j['name'] as String,
      purpose = j['purpose'] as String? ?? '',
      // Reports made before medicines had doses lack the rest.
      forCondition = j['forCondition'] as String? ?? '',
      dose = j['dose'] as String? ?? '',
      frequency = j['frequency'] as String? ?? '',
      duration = j['duration'] as String? ?? '',
      route = j['route'] as String? ?? '',
      maxDaily = j['maxDaily'] as String? ?? '',
      caution = j['caution'] as String? ?? '',
      prescription = j['prescription'] as bool? ?? false,
      source = j['source'] as String? ?? 'knowledge_base';

  final String name;
  final String purpose;
  final String forCondition;
  final String dose;
  final String frequency;
  final String duration;
  final String route;
  final String maxDaily;
  final String caution;
  final bool prescription;

  /// `knowledge_base` or `suggested` (written by the report AI, then
  /// approved by the safety review).
  final String source;
}

/// One measured vital against its normal range.
class VitalReading {
  VitalReading.fromJson(Map<String, dynamic> j)
    : name = j['name'] as String,
      value = j['value'] as String,
      normal = j['normal'] as String? ?? '',
      status = j['status'] as String? ?? 'not_assessed',
      note = j['note'] as String? ?? '';

  final String name;
  final String value;
  final String normal;

  /// `normal`, `low`, `high` or `not_assessed`.
  final String status;
  final String note;
}

class TriageReport {
  TriageReport.fromJson(Map<String, dynamic> j)
    : urgency = Urgency.values.asNameMap()[j['urgency']] ?? Urgency.soon,
      department = j['department'] as String,
      summary = j['summary'] as String,
      precautions = (j['precautions'] as List).cast<String>(),
      doctorNotes = (j['doctorNotes'] as List).cast<String>(),
      vitalFlags = (j['vitalFlags'] as List).cast<String>(),
      knowledgeUsed = j['knowledgeUsed'] as bool,
      disclaimer = j['disclaimer'] as String,
      // Absent from reports generated before the specialist panel existed.
      possibleConditions = [
        for (final c in (j['possibleConditions'] as List? ?? const []))
          PossibleCondition.fromJson(c as Map<String, dynamic>),
      ],
      medicines = [
        for (final m in (j['medicines'] as List? ?? const []))
          Medicine.fromJson(m as Map<String, dynamic>),
      ],
      medicinesNote = j['medicinesNote'] as String? ?? '',
      clinicalSummary = j['clinicalSummary'] as String? ?? '',
      vitals = [
        for (final v in (j['vitalsAssessment'] as List? ?? const []))
          VitalReading.fromJson(v as Map<String, dynamic>),
      ],
      lifestyleAdvice = (j['lifestyleAdvice'] as List? ?? const [])
          .cast<String>(),
      panel = [
        for (final o in (j['panel'] as List? ?? const []))
          SpecialistOpinion.fromJson(o as Map<String, dynamic>),
      ],
      precautionsSource = j['precautionsSource'] as String? ?? '',
      discussion = j['discussion'] as String? ?? '',
      panelNote = j['panelNote'] as String? ?? '',
      language = j['language'] as String? ?? 'en',
      awaitingDoctor = j['awaitingDoctor'] as bool? ?? false,
      patientView = j['patientView'] is Map
          ? PatientView.fromJson(
              (j['patientView'] as Map).cast<String, dynamic>(),
            )
          : null;

  /// The language the patient used at the kiosk (`en`, `ml`).
  final String language;

  /// A doctor reviews this report first: the patient gets their conditions
  /// and medicines in the doctor's signed report.
  final bool awaitingDoctor;

  /// What the patient reads: simple English with Malayalam beneath each
  /// part (backend patient_view.py). Null in reports made before it.
  final PatientView? patientView;

  final Urgency urgency;
  final String department;
  final String summary;
  final List<String> precautions;

  /// `knowledge_base`, `written`, `mixed`, `none` or `unreviewed`.
  final String precautionsSource;
  final List<String> doctorNotes;
  final List<String> vitalFlags;
  final bool knowledgeUsed;
  final String disclaimer;
  final List<PossibleCondition> possibleConditions;
  final List<Medicine> medicines;

  /// Why no medicine is suggested, when none is.
  final String medicinesNote;

  /// For the doctor: what happened to the patient, written after the panel
  /// and checked by the safety review. Empty in older reports.
  final String clinicalSummary;
  final List<VitalReading> vitals;
  final List<String> lifestyleAdvice;
  final List<SpecialistOpinion> panel;

  /// The panel chair's account of where the specialists agreed and differed.
  final String discussion;

  /// Why there is no panel output, when there is none.
  final String panelNote;
}

/// One text for the patient: simple English, and the same text in the
/// visit's language when that is not English ({"en": ..., "ml": ...}).
/// Screens show one of them: [of] the report's language.
class Bi {
  const Bi(this.en, [this.ml, Map<String, String>? other])
    : _other = other ?? const {};

  static Bi? fromJson(Object? j) {
    if (j is! Map) return null;
    final en = (j['en'] as String? ?? '').trim();
    if (en.isEmpty) return null;
    final other = <String, String>{
      for (final e in j.entries)
        if (e.key != 'en' &&
            e.value is String &&
            (e.value as String).trim().isNotEmpty)
          e.key as String: (e.value as String).trim(),
    };
    final ml = other['ml'];
    return Bi(en, ml == null || ml == en ? null : ml, other);
  }

  final String en;
  final String? ml;
  final Map<String, String> _other;

  /// The text in [code], or English when it was not prepared.
  String of(String code) =>
      code == 'en' ? en : (code == 'ml' ? ml : _other[code]) ?? en;
}

class ViewCondition {
  ViewCondition.fromJson(Map<String, dynamic> j)
    : name = Bi.fromJson(j['name']) ?? const Bi(''),
      about = Bi.fromJson(j['about']),
      likelihood = j['likelihood'] as String? ?? 'low',
      probability = (j['probability'] as num?)?.round();

  final Bi name;
  final Bi? about;
  final String likelihood;

  /// The AI's estimate in per cent, as the doctor sees it; null on the
  /// doctor's signed diagnosis and on older reports.
  final int? probability;
}

class ViewMedicine {
  ViewMedicine.fromJson(Map<String, dynamic> j)
    : name = j['name'] as String? ?? '',
      form = j['form'] as String? ?? '',
      strength = j['strength'] as String? ?? '',
      prescription = j['prescription'] as bool? ?? false,
      doctorOnly = j['doctorOnly'] as bool? ?? false,
      howToTake = Bi.fromJson(j['howToTake']),
      purpose = Bi.fromJson(j['purpose']),
      caution = Bi.fromJson(j['caution']);

  final String name;

  /// tablet, capsule, syrup, drops, inhaler, cream...
  final String form;
  final String strength;
  final bool prescription;

  /// Given by the doctor or nurse (injections, emergency care).
  final bool doctorOnly;
  final Bi? howToTake;
  final Bi? purpose;
  final Bi? caution;
}

class ViewVital {
  ViewVital.fromJson(Map<String, dynamic> j)
    : name = j['name'] as String? ?? '',
      value = j['value'] as String? ?? '',
      normal = j['normal'] as String? ?? '',
      status = j['status'] as String? ?? 'not_assessed',
      note = Bi.fromJson(j['note']);

  final String name;
  final String value;
  final String normal;
  final String status;
  final Bi? note;
}

/// The patient's report, as the backend prepared it (patient_view.py).
class PatientView {
  PatientView.fromJson(Map<String, dynamic> j)
    : name = (j['patient'] as Map?)?['name'] as String? ?? '',
      age = (j['patient'] as Map?)?['age'] as int?,
      gender = (j['patient'] as Map?)?['gender'] as String? ?? '',
      phone = (j['patient'] as Map?)?['phone'] as String? ?? '',
      summary = Bi.fromJson(j['summary']),
      symptoms = Bi.fromJson(j['symptoms']),
      duration = Bi.fromJson(j['duration']),
      medicationsTaken = Bi.fromJson(j['medicationsTaken']),
      allergies = Bi.fromJson(j['allergies']),
      conditions = [
        for (final c in (j['conditions'] as List? ?? const []))
          ViewCondition.fromJson((c as Map).cast<String, dynamic>()),
      ],
      medicines = [
        for (final m in (j['medicines'] as List? ?? const []))
          ViewMedicine.fromJson((m as Map).cast<String, dynamic>()),
      ],
      vitals = [
        for (final v in (j['vitals'] as List? ?? const []))
          ViewVital.fromJson((v as Map).cast<String, dynamic>()),
      ],
      vitalFlags = _bis(j['vitalFlags']),
      precautions = _bis(j['precautions']),
      lifestyle = _bis(j['lifestyle']),
      tests = _bis(j['tests']),
      followUp = Bi.fromJson(j['followUp']),
      medicinesNote = Bi.fromJson(j['medicinesNote']),
      note = Bi.fromJson(j['note']),
      language = j['language'] as String? ?? 'en',
      bilingual = j['translated'] as bool? ?? j['bilingual'] as bool? ?? false;

  static List<Bi> _bis(Object? list) => [
    for (final item in (list as List? ?? const [])) ?Bi.fromJson(item),
  ];

  final String name;
  final int? age;
  final String gender;
  final String phone;
  final Bi? summary;
  final Bi? symptoms;
  final Bi? duration;
  final Bi? medicationsTaken;
  final Bi? allergies;
  final List<ViewCondition> conditions;
  final List<ViewMedicine> medicines;
  final List<ViewVital> vitals;
  final List<Bi> vitalFlags;
  final List<Bi> precautions;
  final List<Bi> lifestyle;

  /// Only in a doctor's signed report.
  final List<Bi> tests;
  final Bi? followUp;
  final Bi? medicinesNote;
  final Bi? note;

  /// The language the report is shown in (the visit's): en, ml...
  final String language;

  /// False when the texts could not be put into [language] (offline, or a
  /// failure): they are then shown in English. Always true for English.
  final bool bilingual;
}

/// What the server can do right now.
class ServiceStatus {
  const ServiceStatus({
    this.online = true,
    this.voice = true,
    this.voiceDetail = '',
    this.sms = false,
    this.email = false,
    this.lanAddress = '',
  });

  /// The kiosk cannot reach its own server at all.
  const ServiceStatus.unreachable()
    : online = false,
      voice = false,
      voiceDetail = 'The Medora server cannot be reached.',
      sms = false,
      email = false,
      lanAddress = '';

  ServiceStatus.fromJson(Map<String, dynamic> j)
    : online = j['online'] as bool,
      voice = (j['voice'] as Map)['available'] as bool,
      voiceDetail = (j['voice'] as Map)['detail'] as String? ?? '',
      sms = (j['sms'] as Map)['available'] as bool,
      email = (j['email'] as Map)['available'] as bool,
      lanAddress = j['lanAddress'] as String? ?? '';

  /// The server's address on the local network, for QR codes phones scan.
  final String lanAddress;

  /// False when the server has no internet and runs in offline mode.
  final bool online;
  final bool voice;

  /// Why voice is unavailable (when it is).
  final String voiceDetail;
  final bool sms;
  final bool email;
}

/// What the report being generated is doing right now, as the server
/// reports it. The waiting screen shows exactly this and nothing more.
class ReportProgress {
  ReportProgress.fromJson(Map<String, dynamic> j)
    : stage = j['stage'] as String? ?? 'understanding',
      roster = [
        for (final n in (j['roster'] as List? ?? const [])) n as String,
      ],
      specialists = [
        for (final s in (j['specialists'] as List? ?? const []))
          (
            name: (s as Map)['name'] as String,
            state: s['state'] as String? ?? 'thinking',
          ),
      ];

  /// understanding, evidence, panel, chair, precautions, writing, done,
  /// failed.
  final String stage;

  /// Every specialty the case is screened against.
  final List<String> roster;

  /// The specialists asked, each thinking, took_part, stepped_aside or
  /// unavailable.
  final List<({String name, String state})> specialists;
}

/// The doctor's signed report, as the patient receives it.
class FinalReport {
  FinalReport.fromJson(Map<String, dynamic> j)
    : view = PatientView.fromJson((j['view'] as Map).cast<String, dynamic>()),
      doctorName = (j['doctor'] as Map?)?['name'] as String? ?? '',
      doctorQualification =
          (j['doctor'] as Map?)?['qualification'] as String? ?? '',
      registrationNumber =
          (j['doctor'] as Map?)?['registrationNumber'] as String? ?? '',
      department = (j['doctor'] as Map?)?['department'] as String? ?? '',
      hospitalName = (j['hospital'] as Map?)?['name'] as String? ?? '',
      hospitalAddress = (j['hospital'] as Map?)?['address'] as String? ?? '',
      visitNumber = j['visitNumber'] as String? ?? '',
      finalizedAt = j['finalizedAt'] as String? ?? '';

  final PatientView view;
  final String doctorName;
  final String doctorQualification;
  final String registrationNumber;
  final String department;
  final String hospitalName;
  final String hospitalAddress;
  final String visitNumber;
  final String finalizedAt;
}

/// Where a visit is, for the patient's own page.
class VisitStatus {
  VisitStatus.fromJson(Map<String, dynamic> j)
    : status = j['status'] as String? ?? 'preparing',
      visitNumber = j['visitNumber'] as String? ?? '',
      firstName = j['name'] as String? ?? '',
      doctor = j['doctor'] as String? ?? '',
      report = j['final'] is Map
          ? FinalReport.fromJson((j['final'] as Map).cast<String, dynamic>())
          : null;

  /// preparing, waiting, in_consultation, final, no_review.
  final String status;
  final String visitNumber;
  final String firstName;
  final String doctor;
  final FinalReport? report;
}
