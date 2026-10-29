import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../band/band_service.dart';
import '../state/visit_store.dart';

/// The languages the patient kiosk speaks. The back office stays English.
enum AppLanguage {
  english('en', 'English'),
  malayalam('ml', 'മലയാളം');

  const AppLanguage(this.code, this.nativeName);

  /// Sent to the server with the visit (`language`).
  final String code;

  /// The name in the language itself, for the switch.
  final String nativeName;
}

/// The kiosk's language for the current patient. Back to English when a
/// visit ends, so the next patient starts from the default.
class LanguageController extends Notifier<AppLanguage> {
  /// The visit's language survives a page reload (state/visit_store.dart).
  @override
  AppLanguage build() =>
      AppLanguage.values
          .where((l) => l.code == readVisitLanguage())
          .firstOrNull ??
      AppLanguage.english;

  void set(AppLanguage language) {
    state = language;
    saveVisitLanguage(language.code);
  }

  void reset() {
    state = AppLanguage.english;
    saveVisitLanguage(null);
  }
}

final languageProvider = NotifierProvider<LanguageController, AppLanguage>(
  LanguageController.new,
);

/// The strings for a language code ('en', 'ml'), English for any other:
/// a report is shown in the language of its visit.
S stringsFor(String code) => switch (code) {
  'ml' => const Ml(),
  _ => const En(),
};

final stringsProvider = Provider<S>(
  (ref) => switch (ref.watch(languageProvider)) {
    AppLanguage.english => const En(),
    AppLanguage.malayalam => const Ml(),
  },
);

/// Makes the current [S] available to every widget below it, so screens
/// and small widgets alike read `S.of(context)`.
class StringsScope extends InheritedWidget {
  const StringsScope({super.key, required this.strings, required super.child});

  final S strings;

  @override
  bool updateShouldNotify(StringsScope old) => old.strings != strings;
}

/// Every text the patient kiosk shows. Both languages implement all of it,
/// so a text missing in Malayalam does not compile.
///
/// The Malayalam was written for this kiosk and should be read by a native
/// speaker before patients use it, especially the clinical wording.
abstract class S {
  const S();

  static S of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<StringsScope>()?.strings ??
      const En();

  AppLanguage get language;

  // --- shared ---------------------------------------------------------------
  String get drMedora;
  String get offlineMode;
  String get languageLabel;
  String get stepIntake;
  String get stepVitals;
  String get stepReview;
  String get stepReport;
  String get startOver;
  String get continueLabel;
  String get oneMoment;
  String get finish;
  String get tryAgain;
  String get back;
  String get cancel;
  String get bandNoun;

  // --- welcome --------------------------------------------------------------
  String get goodMorning;
  String get goodAfternoon;
  String get goodEvening;
  String get helloIntro;
  String get introWithBand;
  String get introNoBand;
  String get offlineFormOnly;
  String get offlineNothing;
  String get howToStart;
  String get chooseLanguage;
  String get talkTitle;
  String get talkSubtitle;
  String get needsInternet;
  String get notAvailableNow;
  String get typeTitle;
  String get typeSubtitle;
  String get speakTile;
  String get typeTile;
  String get speakTileSubtitle;
  String get typeTileSubtitle;
  String get allergiesLabel;
  String get allergiesHint;

  /// The first entry means "no allergies" and excludes the others.
  List<String> get allergySuggestions;
  String get allergiesShort;
  String get pregnancyQuestion;
  String pregnancyAnswer(String answer);
  // --- the new flow: phone, health, returning patients, doctor ----------
  String get usePhoneTile;
  String get usePhoneSubtitle;
  String get typeHereInstead;
  String get phoneScanTitle;
  String get phoneScanSteps;
  String get phoneWaiting;
  String get phoneReceived;
  String get phoneExpired;
  String get phoneFillTitle;
  String get phoneFillSubtitle;
  String get phoneSend;
  String get phoneSentTitle;
  String get phoneSentBody;
  String get phoneFollowReport;
  String get healthTitle;
  String get healthSubtitle;
  String get conditionsLabel;
  List<String> get conditionSuggestions;
  String get regularMedicinesLabel;
  String get surgeriesLabel;
  String get habitsLabel;
  String get weightLabel;
  String get visitedTitle;
  String get visitedSubtitle;
  String get visitNumberLabel;
  String get visitNumberShort;
  String get findMe;
  String get thisIsMe;
  String get imNew;
  String get noneFound;
  String get welcomeBack;
  String get savingDetails;
  String get doctorWillSee;
  String visitNumber(String number);
  String get scanForFinal;
  String get bandWipe;
  String get resultTitle;
  String get resultPreparing;
  String get resultWaiting;
  String resultWithDoctor(String doctor);
  String get resultNoReview;
  String get diagnosisLabel;
  String get prescribedLabel;
  String get testsLabel;
  String get followUpLabel;
  String get signedBy;
  String get registrationLabel;
  String get downloadPrescription;
  String get noMedicinePrescribed;
  String get simulatorTitle;
  String get simulatorHint;
  String get systolic;
  String get diastolic;
  String get pause;
  String get resume;
  String get paused;
  String get pausedDetail;
  String get notedSoFar;
  String get yourProblem;

  // --- form -----------------------------------------------------------------
  String get formTitle;
  String get formSubtitle;
  String stepOf(int n, int total);
  String get aboutYou;
  String get aboutYouSubtitle;
  String get fullName;
  String get age;
  String get phone;
  String get gender;
  String genderName(String gender);
  String get emailOptional;
  String get bothering;
  String get botheringSubtitle;
  String get feelingLabel;
  String get feelingHint;
  String get sinceWhen;
  String get durationLabel;
  String get durationHint;
  String get medication;
  String get medicationSubtitle;
  String get medicationLabel;
  String get medicationHint;
  String get enterName;
  String get enterAge;
  String get validAge;
  String get enterPhone;
  String get validPhone;
  String get validEmail;
  String get validName;
  String get selectGender;
  String get describeSymptoms;

  /// Tap-to-select answers. The words go into the text field as they are.
  List<String> get symptomSuggestions;
  List<String> get durationSuggestions;

  /// The first entry means "nothing taken" and excludes the others.
  List<String> get medicationSuggestions;

  // --- vitals ---------------------------------------------------------------
  String get vitalsTitle;
  String vitalsTakes(int minutes);
  String get continueToReview;
  String vitalName(VitalSign sign);
  String get notMeasured;
  String get putOnBand;
  String get wearInstruction;
  String get connectingBand;
  String get connectingDetail;
  String get preparingBand;
  String connectedTo(String device);
  String measuring(VitalSign sign);
  String get keepStill;
  String keepStillUpTo(int seconds);
  String get vitalsTaken;
  String get allReadingsIn;
  String couldNotRead(Iterable<VitalSign> missed);
  String get didNotWork;
  String get bandStopped;
  String get startMeasuring;
  String get vitalsFirst;
  String get vitalsNeededHere;
  String get measureAgain;
  String get continueWithoutVitals;

  /// A message from the band driver or the browser, in this language when
  /// it is one we know; otherwise as it came.
  String bandMessage(String english);

  // --- review ---------------------------------------------------------------
  String get reviewTitle;
  String get reviewSubtitleBand;
  String get reviewSubtitle;
  String get missingDetails;
  String get vitalsNotNeeded;
  String get vitalsNotCaptured;
  String get confirmAndReport;
  String get notSaved;

  // --- voice ----------------------------------------------------------------
  String get connectingMedora;
  String get takingVitals;
  String get medoraSpeaking;
  String get listening;
  String get thankYou;
  String get medoraUnavailable;
  String get speakNaturally;
  String get voiceUnavailable;
  String get toldIsSaved;
  String get canTypeInstead;
  String get continueWithWhatITold;
  String get endConversation;
  String get typeInstead;
  String get conversationAppears;
  String get you;
  String get nameLabel;
  String get symptomsLabel;
  String get medicationsLabel;

  // --- report ---------------------------------------------------------------
  String get yourReport;
  String get noIntake;
  String get reportTakesMinute;
  String get reportFailed;
  String get summary;
  String get yourVitals;
  String get measuredByBand;
  String normalRange(String range);
  String vitalStatus(String status);
  String get medicines;
  String get medicinesForDoctor;
  String get medicinesDoctorOnly;
  String get doctorGives;
  String get prescription;
  String forCondition(String condition);
  String forDuration(String duration);
  String atMost(String amount);
  String get whileYouWait;
  String get lifestyleAdvice;
  String get forDoctorReview;
  String get getMyReport;
  String get textMessage;
  String get smsNotSetUp;
  String get email;
  String get emailNotSetUp;
  String get noEmail;
  String get downloadPdf;
  String get send;
  String get sending;
  String get sendAgain;
  String sentBy(String channel);
  String get couldNotOpen;
  String get noKnowledgeBase;
  String urgency(String urgency);
  String department(String department);
  String get possibleConditions;
  String get notADiagnosis;
  String get reportDisclaimer;
  String likelihood(String likelihood);
  String get reportInEnglish;
  String get patientLabel;
  String get toldUs;
  String get medicinesTaken;
  String get howToTake;
  String get whatFor;
  String get cautionLabel;

  /// A dosage form ("tablet", "syrup"...) as the patient would say it.
  String formName(String form);

  /// A vital's name as the server writes it ("Heart rate").
  String vitalLabel(String english);

  // --- waiting screen ---------------------------------------------------------
  String specialist(String name);
  String specialistState(String state);
  String get understanding;
  String get preparingCase;
  String screening(int count);
  String get checkingKnowledge;
  String get matchingSymptoms;
  String get reviewingCase;
  String get fewMoments;
  String get bringingTogether;
  String get specialistsReviewing;
  String answered(int done, int total, int aside);
  String get reachingConclusion;
  String tookPart(int count);
  String get writingReport;
  String get preparingAdvice;
  String get reportReady;
  String get writingSummary;
  List<String> get reportSteps;
}

/// English.
class En extends S {
  const En();

  @override
  AppLanguage get language => AppLanguage.english;

  @override
  String get drMedora => 'Dr. Medora';
  @override
  String get offlineMode => 'Offline mode';
  @override
  String get languageLabel => 'Language';
  @override
  String get stepIntake => 'Intake';
  @override
  String get stepVitals => 'Vitals';
  @override
  String get stepReview => 'Review';
  @override
  String get stepReport => 'Report';
  @override
  String get startOver => 'Start over';
  @override
  String get continueLabel => 'Continue';
  @override
  String get oneMoment => 'One moment…';
  @override
  String get finish => 'Finish';
  @override
  String get tryAgain => 'Try again';
  @override
  String get back => 'Back';
  @override
  String get cancel => 'Cancel';
  @override
  String get bandNoun => 'band';

  @override
  String get goodMorning => 'Good morning.';
  @override
  String get goodAfternoon => 'Good afternoon.';
  @override
  String get goodEvening => 'Good evening.';
  @override
  String get helloIntro => "Hello, I'm Dr. Medora";
  @override
  String get introWithBand =>
      "Tell me what brings you in. I'll ask a few questions, take your vitals "
      'if they are needed, and prepare a note for your doctor.';
  @override
  String get introNoBand =>
      "Tell me what brings you in. I'll ask a few questions and prepare a "
      'note for your doctor.';
  @override
  String get offlineFormOnly =>
      'There is no internet connection right now. You can still type your '
      'details; talking to Dr. Medora comes back with the connection.';
  @override
  String get offlineNothing =>
      'Medora needs an internet connection and is offline right now. Please '
      'ask the hospital staff for help.';
  @override
  String get howToStart => 'HOW WOULD YOU LIKE TO START?';
  @override
  String get chooseLanguage => 'Choose your language';
  @override
  String get talkTitle => 'Talk to Dr. Medora';
  @override
  String get talkSubtitle => 'Answer a few questions by voice';
  @override
  String get needsInternet => 'Needs an internet connection';
  @override
  String get notAvailableNow => 'Not available right now';
  @override
  String get typeTitle => 'Type my details';
  @override
  String get typeSubtitle => 'Tap your answers on screen';
  @override
  String get speakTile => 'Speak';
  @override
  String get typeTile => 'Type';
  @override
  String get speakTileSubtitle => 'Talk with Dr. Medora';
  @override
  String get typeTileSubtitle => 'Fill in on screen';
  @override
  String get allergiesLabel => 'Any allergies to medicines or injections?';
  @override
  String get allergiesHint => 'Tap above, or type what you react to';
  @override
  List<String> get allergySuggestions => const [
    'No allergies',
    'Penicillin',
    'Sulfa drugs',
    'Painkillers',
    'An injection',
    'Food',
  ];
  @override
  String get allergiesShort => 'Allergies';
  @override
  String get pregnancyQuestion => 'Could you be pregnant?';
  @override
  String pregnancyAnswer(String answer) => switch (answer) {
    'yes' => 'Yes',
    'no' => 'No',
    _ => 'Not sure',
  };
  @override
  String get usePhoneTile => 'Use my phone';
  @override
  String get usePhoneSubtitle => 'Scan a code, fill in on your phone';
  @override
  String get typeHereInstead => 'No phone? Type on this screen';
  @override
  String get phoneScanTitle => 'Scan this code with your phone';
  @override
  String get phoneScanSteps =>
      'Open your phone camera, point it at the code and tap the link. Fill in '
      'your details on your phone; this screen moves on by itself.';
  @override
  String get phoneWaiting => 'Waiting for your phone…';
  @override
  String get phoneReceived => 'Your details have arrived.';
  @override
  String get phoneExpired => 'This code has expired. Go back and start again.';
  @override
  String get phoneFillTitle => 'Your visit details';
  @override
  String get phoneFillSubtitle =>
      'Fill this in on your phone. When you send it, go back to the kiosk.';
  @override
  String get phoneSend => 'Send to the kiosk';
  @override
  String get phoneSentTitle => 'Sent. Go back to the kiosk.';
  @override
  String get phoneSentBody =>
      'The kiosk will take your vitals if they are needed. Keep this page '
      'open: your report will appear here.';
  @override
  String get phoneFollowReport => 'Open my report';
  @override
  String get healthTitle => 'Your health';
  @override
  String get healthSubtitle =>
      'Long-term conditions and medicines you take every day. You can skip this.';
  @override
  String get conditionsLabel => 'Any long-term condition?';
  @override
  List<String> get conditionSuggestions => const [
    'None',
    'Diabetes',
    'High blood pressure',
    'Asthma',
    'Heart disease',
    'Thyroid',
    'Kidney disease',
  ];
  @override
  String get regularMedicinesLabel => 'Medicines you take every day';
  @override
  String get surgeriesLabel => 'Past operations (optional)';
  @override
  String get habitsLabel => 'Smoking, tobacco or alcohol (optional)';
  @override
  String get weightLabel => 'Weight in kg (needed for children)';
  @override
  String get visitedTitle => 'Have you visited this hospital before?';
  @override
  String get visitedSubtitle =>
      'Type the visit number printed on an earlier report, then pick your name.';
  @override
  String get visitNumberLabel => 'Visit number';
  @override
  String get visitNumberShort =>
      'A visit number has 6 letters and numbers, like AB12CD.';
  @override
  String get findMe => 'Find me';
  @override
  String get thisIsMe => 'This is me';
  @override
  String get imNew => "I'm new";
  @override
  String get noneFound =>
      'No visit has this number. You will be registered as new.';
  @override
  String get welcomeBack =>
      'Welcome back. Your doctor will see your earlier visits.';
  @override
  String get savingDetails => 'Saving your details…';
  @override
  String get doctorWillSee =>
      'A doctor will see you and decide your medicines. Please wait to be called.';
  @override
  String visitNumber(String number) => 'Your visit number: $number';
  @override
  String get scanForFinal =>
      'Scan to get your doctor\'s final report on your phone.';
  @override
  String get bandWipe => 'Staff: wipe the band before the next patient.';
  @override
  String get resultTitle => 'Your visit';
  @override
  String get resultPreparing => 'Medora is preparing your report.';
  @override
  String get resultWaiting =>
      'Your details are with the doctors. Please wait to be called; your '
      'final report will appear here after your consultation.';
  @override
  String resultWithDoctor(String doctor) =>
      '$doctor is seeing you now. Your report will appear here when they finish.';
  @override
  String get resultNoReview =>
      'Your report was given at the kiosk. Ask the staff if you need a copy.';
  @override
  String get diagnosisLabel => 'Diagnosis';
  @override
  String get prescribedLabel => 'Medicines prescribed';
  @override
  String get testsLabel => 'Tests';
  @override
  String get followUpLabel => 'Follow-up';
  @override
  String get signedBy => 'Signed by';
  @override
  String get registrationLabel => 'Registration no.';
  @override
  String get downloadPrescription => 'Download prescription (PDF)';
  @override
  String get noMedicinePrescribed => 'No medicine was prescribed.';
  @override
  String get simulatorTitle => 'Band simulator';
  @override
  String get simulatorHint =>
      'Set the vitals here, then tap Start measuring below.';
  @override
  String get systolic => 'Blood pressure (upper)';
  @override
  String get diastolic => 'Blood pressure (lower)';
  @override
  String get pause => 'Pause';
  @override
  String get notedSoFar => 'What Dr. Medora has noted';
  @override
  String get yourProblem => 'Your problem';
  @override
  String get resume => 'Resume';
  @override
  String get paused => 'Paused';
  @override
  String get pausedDetail =>
      'The microphone is off. Tap Resume when you are ready to continue.';

  @override
  String get formTitle => 'Tell us about yourself';
  @override
  String get formSubtitle =>
      'Three quick steps, mostly taps. It takes about a minute.';
  @override
  String stepOf(int n, int total) => 'STEP $n OF $total';
  @override
  String get aboutYou => 'About you';
  @override
  String get aboutYouSubtitle => 'So the doctor knows who the report is for.';
  @override
  String get fullName => 'Full name';
  @override
  String get age => 'Age';
  @override
  String get phone => 'Phone number';
  @override
  String get gender => 'Gender';
  @override
  String genderName(String gender) => switch (gender) {
    'male' => 'Male',
    'female' => 'Female',
    _ => 'Other',
  };
  @override
  String get emailOptional => 'Email (optional)';
  @override
  String get bothering => "What's bothering you?";
  @override
  String get botheringSubtitle =>
      'Tap everything you feel, then add details if you like.';
  @override
  String get feelingLabel => 'What are you feeling?';
  @override
  String get feelingHint => 'Tap above, or describe it in your own words';
  @override
  String get sinceWhen => 'Since when?';
  @override
  String get durationLabel => 'How long have you had them?';
  @override
  String get durationHint => 'For example: 3 days';
  @override
  String get medication => 'Medication and allergies';
  @override
  String get medicationSubtitle =>
      'Anything you have already taken for this, and any allergies.';
  @override
  String get medicationLabel => 'Have you taken any medication for this?';
  @override
  String get medicationHint => 'Tap above, or type the name';
  @override
  String get enterName => 'Enter your name';
  @override
  String get enterAge => 'Enter your age';
  @override
  String get validAge => 'Enter a valid age';
  @override
  String get enterPhone => 'Enter a phone number for your report';
  @override
  String get validPhone => 'Enter a 10-digit mobile number';
  @override
  String get validEmail => 'Enter a valid email, like name@gmail.com';
  @override
  String get validName => 'Use letters only, no numbers';
  @override
  String get selectGender => 'Select your gender';
  @override
  String get describeSymptoms => 'Describe your symptoms';
  @override
  List<String> get symptomSuggestions => const [
    'Fever',
    'Cough',
    'Cold or runny nose',
    'Sore throat',
    'Headache',
    'Body pain',
    'Stomach pain',
    'Vomiting',
    'Loose motions',
    'Chest pain',
    'Breathing difficulty',
    'Dizziness',
    'Tiredness',
    'Skin rash or itching',
    'Back or joint pain',
    'Burning when passing urine',
  ];
  @override
  List<String> get durationSuggestions => const [
    'Since today',
    '2-3 days',
    'About a week',
    '2 weeks',
    'More than a month',
  ];
  @override
  List<String> get medicationSuggestions => const [
    'None',
    'Paracetamol',
    'Ibuprofen',
    'Cough syrup',
    'Antacid',
    'Antibiotics',
    'Allergy tablet',
    'Inhaler',
  ];

  @override
  String get vitalsTitle => "Let's take your vitals";
  @override
  String vitalsTakes(int minutes) => minutes <= 1
      ? 'The band takes about a minute.'
      : 'The band takes about $minutes minutes.';
  @override
  String get continueToReview => 'Continue to review';
  @override
  String vitalName(VitalSign sign) => switch (sign) {
    VitalSign.heartRate => 'Heart rate',
    VitalSign.spo2 => 'Oxygen (SpO2)',
    VitalSign.temperature => 'Temperature',
    VitalSign.bloodPressure => 'Blood pressure',
  };
  @override
  String get notMeasured => 'Not measured';
  @override
  String get putOnBand => 'Put on the band';
  @override
  String get wearInstruction =>
      'Wear the band snugly on your wrist, just above the wrist bone, with '
      'the sensor touching your skin. Then tap Start measuring.';
  @override
  String get connectingBand => 'Connecting to the band';
  @override
  String get connectingDetail =>
      'If a window opens, choose the band in the list and press Pair.';
  @override
  String get preparingBand => 'Getting the band ready';
  @override
  String connectedTo(String device) => 'Connected to $device.';
  @override
  String measuring(VitalSign sign) =>
      'Measuring your ${vitalName(sign).toLowerCase()}';
  @override
  String get keepStill => 'Keep your hand still.';
  @override
  String keepStillUpTo(int seconds) =>
      'Keep your hand still. Up to $seconds seconds.';
  @override
  String get vitalsTaken => 'Vitals taken';
  @override
  String get allReadingsIn => 'All readings are in.';
  @override
  String couldNotRead(Iterable<VitalSign> missed) =>
      'Could not read: ${missed.map((s) => vitalName(s).toLowerCase()).join(', ')}.';
  @override
  String get didNotWork => 'That did not work';
  @override
  String get bandStopped => 'The band stopped responding.';
  @override
  String get startMeasuring => 'Start measuring';
  @override
  String get vitalsFirst => 'Please take your vitals with the band first.';
  @override
  String get vitalsNeededHere =>
      'Your vitals are still needed. Put on the band and tap Start measuring.';
  @override
  String get measureAgain => 'Measure again';
  @override
  String get continueWithoutVitals => 'Continue without vitals';
  @override
  String bandMessage(String english) => english;

  @override
  String get reviewTitle => 'Is everything correct?';
  @override
  String get reviewSubtitleBand =>
      'Tap any field to change it. Your vitals come from the band and cannot '
      'be edited.';
  @override
  String get reviewSubtitle => 'Tap any field to change it.';
  @override
  String get missingDetails =>
      'Some details are missing. Please fill them in below.';
  @override
  String get vitalsNotNeeded =>
      'Vitals were not needed for what you described.';
  @override
  String get vitalsNotCaptured =>
      'Vitals have not been captured from the band.';
  @override
  String get confirmAndReport => 'Confirm and get my report';
  @override
  String get notSaved => 'Your details were not saved.';

  @override
  String get connectingMedora => 'Connecting to Dr. Medora';
  @override
  String get takingVitals => 'Taking your vitals';
  @override
  String get medoraSpeaking => 'Dr. Medora is speaking';
  @override
  String get listening => "I'm listening";
  @override
  String get thankYou => 'Thank you';
  @override
  String get medoraUnavailable => 'Dr. Medora is not available';
  @override
  String get speakNaturally =>
      'Speak naturally. You can interrupt at any time.';
  @override
  String get voiceUnavailable => 'The voice agent is not available.';
  @override
  String get toldIsSaved => 'Your answers so far are saved.';
  @override
  String get canTypeInstead => 'You can type your details instead.';
  @override
  String get continueWithWhatITold => 'Check my answers';
  @override
  String get endConversation => 'End conversation';
  @override
  String get typeInstead => 'Type instead';
  @override
  String get conversationAppears => 'Your conversation will appear here.';
  @override
  String get you => 'You';
  @override
  String get nameLabel => 'Name';
  @override
  String get symptomsLabel => 'Symptoms';
  @override
  String get medicationsLabel => 'Medications';

  @override
  String get yourReport => 'Your report';
  @override
  String get noIntake => 'There is no confirmed intake to report on.';
  @override
  String get reportTakesMinute =>
      'This takes about a minute. Please stay here.';
  @override
  String get reportFailed => 'The report could not be generated.';
  @override
  String get summary => 'Summary';
  @override
  String get yourVitals => 'Your vitals';
  @override
  String get measuredByBand => 'Measured by the smart band.';
  @override
  String normalRange(String range) => 'Normal: $range';
  @override
  String vitalStatus(String status) => switch (status) {
    'normal' => 'Normal',
    'low' => 'Low',
    'high' => 'High',
    _ => 'Not judged',
  };
  @override
  String get medicines => 'Medicines';
  @override
  String get medicinesForDoctor => 'Medications the doctor may consider';
  @override
  String get medicinesDoctorOnly =>
      'The doctor decides on these. Do not take, stop or change any medicine '
      'until your doctor tells you.';
  @override
  String get doctorGives =>
      'Only the doctor or nurse gives this. Do not take it yourself.';
  @override
  String get prescription => 'Prescription';
  @override
  String forCondition(String condition) => 'For $condition';
  @override
  String forDuration(String duration) => 'for $duration';
  @override
  String atMost(String amount) => 'At most $amount in 24 hours';
  @override
  String get whileYouWait => 'While you wait';
  @override
  String get lifestyleAdvice => 'Lifestyle advice';
  @override
  String get forDoctorReview => "For the doctor's review";
  @override
  String get getMyReport => 'Get my report';
  @override
  String get textMessage => 'Text message';
  @override
  String get smsNotSetUp => 'Text messages are not set up yet';
  @override
  String get email => 'Email';
  @override
  String get emailNotSetUp => 'Email is not set up yet';
  @override
  String get noEmail => 'No email address given';
  @override
  String get downloadPdf => 'Download PDF';
  @override
  String get send => 'Send';
  @override
  String get sending => 'Sending';
  @override
  String get sendAgain => 'Send again';
  @override
  String sentBy(String channel) => 'Report sent by ${channel.toLowerCase()}.';
  @override
  String get couldNotOpen => 'The report could not be opened.';
  @override
  String get noKnowledgeBase => 'Generated without the medical knowledge base.';
  @override
  String urgency(String urgency) => switch (urgency) {
    'routine' => 'Routine',
    'soon' => 'See a doctor soon',
    'urgent' => 'Urgent',
    _ => 'Emergency: tell the staff now',
  };
  @override
  String department(String department) => 'Department: $department';
  @override
  String get possibleConditions => 'Possible conditions';
  @override
  String get reportDisclaimer =>
      'This is an automated summary for your doctor to confirm. It is not a '
      'diagnosis or a prescription.';
  @override
  String get notADiagnosis =>
      'For your doctor to confirm. These are not a diagnosis.';
  @override
  String likelihood(String likelihood) => switch (likelihood) {
    'high' => 'More likely',
    'medium' => 'Possible',
    _ => 'Less likely',
  };
  @override
  String get reportInEnglish =>
      'The Malayalam version of this report could not be prepared.';
  @override
  String get patientLabel => 'Patient';
  @override
  String get toldUs => 'What you told us';
  @override
  String get medicinesTaken => 'Medicines already taken';
  @override
  String get howToTake => 'How to take';
  @override
  String get whatFor => 'What it is for';
  @override
  String get cautionLabel => 'Caution';
  @override
  String formName(String form) => form;
  @override
  String vitalLabel(String english) => english;

  @override
  String specialist(String name) => name;
  @override
  String specialistState(String state) => switch (state) {
    'thinking' => 'reviewing…',
    'took_part' => 'opinion given',
    'stepped_aside' => 'not their field',
    _ => 'unavailable',
  };
  @override
  String get understanding => 'Understanding your symptoms';
  @override
  String get preparingCase => 'Preparing your case for the specialists.';
  @override
  String screening(int count) =>
      'Screening your case against $count specialties.';
  @override
  String get checkingKnowledge => 'Checking the medical knowledge base';
  @override
  String get matchingSymptoms =>
      'Matching your symptoms with known conditions.';
  @override
  String get reviewingCase => 'Reviewing your case';
  @override
  String get fewMoments => 'This takes a few moments.';
  @override
  String get bringingTogether => 'Bringing the review together';
  @override
  String get specialistsReviewing => 'Specialists are reviewing your case';
  @override
  String answered(int done, int total, int aside) =>
      '$done of $total have given their view'
      '${aside > 0 ? ', $aside found it outside their field' : ''}.';
  @override
  String get reachingConclusion => 'The panel is reaching a conclusion';
  @override
  String tookPart(int count) =>
      '$count ${count == 1 ? 'specialist' : 'specialists'} took part.';
  @override
  String get writingReport => 'Writing your report';
  @override
  String get preparingAdvice => 'Preparing medicines and advice for your case.';
  @override
  String get reportReady => 'Your report is ready';
  @override
  String get writingSummary => 'Writing your summary';
  @override
  List<String> get reportSteps => const [
    'Your symptoms',
    'Knowledge base',
    'Specialist panel',
    'Your advice',
  ];
}

/// Malayalam.
class Ml extends S {
  const Ml();

  @override
  AppLanguage get language => AppLanguage.malayalam;

  @override
  String get drMedora => 'ഡോക്ടർ മെഡോറ';
  @override
  String get offlineMode => 'ഓഫ്‌ലൈൻ';
  @override
  String get languageLabel => 'ഭാഷ';
  @override
  String get stepIntake => 'വിവരങ്ങൾ';
  @override
  String get stepVitals => 'പരിശോധന';
  @override
  String get stepReview => 'ഉറപ്പാക്കൽ';
  @override
  String get stepReport => 'റിപ്പോർട്ട്';
  @override
  String get startOver => 'വീണ്ടും തുടങ്ങുക';
  @override
  String get continueLabel => 'തുടരുക';
  @override
  String get oneMoment => 'ഒരു നിമിഷം…';
  @override
  String get finish => 'പൂർത്തിയാക്കുക';
  @override
  String get tryAgain => 'വീണ്ടും ശ്രമിക്കുക';
  @override
  String get back => 'തിരികെ';
  @override
  String get cancel => 'റദ്ദാക്കുക';
  @override
  String get bandNoun => 'ബാൻഡ്';

  @override
  String get goodMorning => 'സുപ്രഭാതം.';
  @override
  String get goodAfternoon => 'നമസ്കാരം.';
  @override
  String get goodEvening => 'ശുഭസന്ധ്യ.';
  @override
  String get helloIntro => 'ഞാൻ ഡോക്ടർ മെഡോറ';
  @override
  String get introWithBand =>
      'എന്താണ് ബുദ്ധിമുട്ട് എന്ന് എന്നോട് പറയൂ. ഞാൻ കുറച്ച് ചോദ്യങ്ങൾ ചോദിക്കും, '
      'ആവശ്യമെങ്കിൽ നിങ്ങളുടെ ഹൃദയമിടിപ്പും ഓക്സിജൻ നിലയും പരിശോധിക്കും, '
      'ഡോക്ടർക്കായി ഒരു കുറിപ്പ് തയ്യാറാക്കും.';
  @override
  String get introNoBand =>
      'എന്താണ് ബുദ്ധിമുട്ട് എന്ന് എന്നോട് പറയൂ. ഞാൻ കുറച്ച് ചോദ്യങ്ങൾ ചോദിച്ച് '
      'ഡോക്ടർക്കായി ഒരു കുറിപ്പ് തയ്യാറാക്കും.';
  @override
  String get offlineFormOnly =>
      'ഇപ്പോൾ ഇന്റർനെറ്റ് കണക്ഷൻ ഇല്ല. നിങ്ങളുടെ വിവരങ്ങൾ ടൈപ്പ് ചെയ്ത് നൽകാം; '
      'ഡോക്ടർ മെഡോറയോട് സംസാരിക്കാൻ കണക്ഷൻ തിരികെ വരണം.';
  @override
  String get offlineNothing =>
      'മെഡോറയ്ക്ക് ഇന്റർനെറ്റ് കണക്ഷൻ ആവശ്യമാണ്, ഇപ്പോൾ അത് ലഭ്യമല്ല. ദയവായി '
      'ആശുപത്രി ജീവനക്കാരുടെ സഹായം തേടുക.';
  @override
  String get howToStart => 'എങ്ങനെ തുടങ്ങണം?';
  @override
  String get chooseLanguage => 'ഭാഷ തിരഞ്ഞെടുക്കുക';
  @override
  String get talkTitle => 'ഡോക്ടർ മെഡോറയോട് സംസാരിക്കുക';
  @override
  String get talkSubtitle => 'ശബ്ദത്തിലൂടെ കുറച്ച് ചോദ്യങ്ങൾക്ക് മറുപടി നൽകുക';
  @override
  String get needsInternet => 'ഇന്റർനെറ്റ് കണക്ഷൻ ആവശ്യമാണ്';
  @override
  String get notAvailableNow => 'ഇപ്പോൾ ലഭ്യമല്ല';
  @override
  String get typeTitle => 'വിവരങ്ങൾ ടൈപ്പ് ചെയ്യുക';
  @override
  String get typeSubtitle => 'സ്ക്രീനിൽ തൊട്ട് ഉത്തരങ്ങൾ തിരഞ്ഞെടുക്കുക';
  @override
  String get speakTile => 'സംസാരിക്കുക';
  @override
  String get typeTile => 'ടൈപ്പ് ചെയ്യുക';
  @override
  String get speakTileSubtitle => 'ഡോക്ടർ മെഡോറയോട് സംസാരിക്കാം';
  @override
  String get typeTileSubtitle => 'സ്ക്രീനിൽ പൂരിപ്പിക്കാം';
  @override
  String get allergiesLabel => 'ഏതെങ്കിലും മരുന്നിനോ ഇഞ്ചക്ഷനോ അലർജിയുണ്ടോ?';
  @override
  String get allergiesHint =>
      'മുകളിൽ തൊടുക, അല്ലെങ്കിൽ എന്തിനാണ് അലർജി എന്ന് എഴുതുക';
  @override
  List<String> get allergySuggestions => const [
    'അലർജിയില്ല',
    'പെൻസിലിൻ',
    'സൾഫ മരുന്നുകൾ',
    'വേദനസംഹാരികൾ',
    'ഇഞ്ചക്ഷൻ',
    'ഭക്ഷണം',
  ];
  @override
  String get allergiesShort => 'അലർജി';
  @override
  String get pregnancyQuestion => 'ഇപ്പോൾ ഗർഭിണിയാകാൻ സാധ്യതയുണ്ടോ?';
  @override
  String pregnancyAnswer(String answer) => switch (answer) {
    'yes' => 'ഉണ്ട്',
    'no' => 'ഇല്ല',
    _ => 'ഉറപ്പില്ല',
  };
  @override
  String get usePhoneTile => 'എന്റെ ഫോൺ ഉപയോഗിക്കുക';
  @override
  String get usePhoneSubtitle => 'കോഡ് സ്കാൻ ചെയ്ത് ഫോണിൽ പൂരിപ്പിക്കാം';
  @override
  String get typeHereInstead => 'ഫോൺ ഇല്ലേ? ഈ സ്ക്രീനിൽ ടൈപ്പ് ചെയ്യുക';
  @override
  String get phoneScanTitle => 'ഈ കോഡ് ഫോൺ ഉപയോഗിച്ച് സ്കാൻ ചെയ്യുക';
  @override
  String get phoneScanSteps =>
      'ഫോണിലെ ക്യാമറ തുറന്ന് കോഡിലേക്ക് പിടിച്ച് ലിങ്കിൽ തൊടുക. ഫോണിൽ വിവരങ്ങൾ '
      'പൂരിപ്പിക്കുക; ഈ സ്ക്രീൻ സ്വയം മുന്നോട്ട് പോകും.';
  @override
  String get phoneWaiting => 'നിങ്ങളുടെ ഫോണിനായി കാത്തിരിക്കുന്നു…';
  @override
  String get phoneReceived => 'നിങ്ങളുടെ വിവരങ്ങൾ ലഭിച്ചു.';
  @override
  String get phoneExpired =>
      'ഈ കോഡിന്റെ സമയം കഴിഞ്ഞു. തിരികെ പോയി വീണ്ടും തുടങ്ങുക.';
  @override
  String get phoneFillTitle => 'നിങ്ങളുടെ സന്ദർശന വിവരങ്ങൾ';
  @override
  String get phoneFillSubtitle =>
      'ഇത് ഫോണിൽ പൂരിപ്പിക്കുക. അയച്ച ശേഷം കിയോസ്കിലേക്ക് തിരികെ പോകുക.';
  @override
  String get phoneSend => 'കിയോസ്കിലേക്ക് അയയ്ക്കുക';
  @override
  String get phoneSentTitle => 'അയച്ചു. കിയോസ്കിലേക്ക് തിരികെ പോകുക.';
  @override
  String get phoneSentBody =>
      'ആവശ്യമെങ്കിൽ കിയോസ്ക് നിങ്ങളുടെ പരിശോധന നടത്തും. ഈ പേജ് തുറന്നുവയ്ക്കുക: '
      'നിങ്ങളുടെ റിപ്പോർട്ട് ഇവിടെ വരും.';
  @override
  String get phoneFollowReport => 'എന്റെ റിപ്പോർട്ട് തുറക്കുക';
  @override
  String get healthTitle => 'നിങ്ങളുടെ ആരോഗ്യം';
  @override
  String get healthSubtitle =>
      'ദീർഘകാല രോഗങ്ങളും ദിവസവും കഴിക്കുന്ന മരുന്നുകളും. ഇത് ഒഴിവാക്കാം.';
  @override
  String get conditionsLabel => 'ഏതെങ്കിലും ദീർഘകാല രോഗമുണ്ടോ?';
  @override
  List<String> get conditionSuggestions => const [
    'ഒന്നുമില്ല',
    'പ്രമേഹം',
    'ഉയർന്ന രക്തസമ്മർദ്ദം',
    'ആസ്ത്മ',
    'ഹൃദ്രോഗം',
    'തൈറോയ്ഡ്',
    'വൃക്കരോഗം',
  ];
  @override
  String get regularMedicinesLabel => 'ദിവസവും കഴിക്കുന്ന മരുന്നുകൾ';
  @override
  String get surgeriesLabel => 'മുമ്പ് നടന്ന ശസ്ത്രക്രിയകൾ (നിർബന്ധമില്ല)';
  @override
  String get habitsLabel => 'പുകവലി, പുകയില അല്ലെങ്കിൽ മദ്യപാനം (നിർബന്ധമില്ല)';
  @override
  String get weightLabel => 'ഭാരം കിലോഗ്രാമിൽ (കുട്ടികൾക്ക് ആവശ്യം)';
  @override
  String get visitedTitle => 'മുമ്പ് ഈ ആശുപത്രിയിൽ വന്നിട്ടുണ്ടോ?';
  @override
  String get visitedSubtitle =>
      'മുമ്പത്തെ റിപ്പോർട്ടിലുള്ള സന്ദർശന നമ്പർ നൽകി, നിങ്ങളുടെ പേര് തിരഞ്ഞെടുക്കുക.';
  @override
  String get visitNumberLabel => 'സന്ദർശന നമ്പർ';
  @override
  String get visitNumberShort =>
      'സന്ദർശന നമ്പറിൽ 6 അക്ഷരങ്ങളും അക്കങ്ങളും ഉണ്ട്, ഉദാ. AB12CD.';
  @override
  String get findMe => 'എന്നെ കണ്ടെത്തുക';
  @override
  String get thisIsMe => 'ഇത് ഞാനാണ്';
  @override
  String get imNew => 'ഞാൻ പുതിയ ആളാണ്';
  @override
  String get noneFound =>
      'ഈ നമ്പറിൽ ഒരു സന്ദർശനവും ഇല്ല. പുതിയ ആളായി രജിസ്റ്റർ ചെയ്യും.';
  @override
  String get welcomeBack =>
      'വീണ്ടും സ്വാഗതം. നിങ്ങളുടെ മുൻ സന്ദർശനങ്ങൾ ഡോക്ടർ കാണും.';
  @override
  String get savingDetails => 'നിങ്ങളുടെ വിവരങ്ങൾ സേവ് ചെയ്യുന്നു…';
  @override
  String get doctorWillSee =>
      'ഒരു ഡോക്ടർ നിങ്ങളെ കണ്ട് മരുന്നുകൾ തീരുമാനിക്കും. വിളിക്കുന്നത് വരെ കാത്തിരിക്കുക.';
  @override
  String visitNumber(String number) => 'നിങ്ങളുടെ സന്ദർശന നമ്പർ: $number';
  @override
  String get scanForFinal =>
      'ഡോക്ടറുടെ അന്തിമ റിപ്പോർട്ട് ഫോണിൽ ലഭിക്കാൻ സ്കാൻ ചെയ്യുക.';
  @override
  String get bandWipe => 'ജീവനക്കാർ: അടുത്ത രോഗിക്ക് മുമ്പ് ബാൻഡ് തുടയ്ക്കുക.';
  @override
  String get resultTitle => 'നിങ്ങളുടെ സന്ദർശനം';
  @override
  String get resultPreparing => 'മെഡോറ നിങ്ങളുടെ റിപ്പോർട്ട് തയ്യാറാക്കുന്നു.';
  @override
  String get resultWaiting =>
      'നിങ്ങളുടെ വിവരങ്ങൾ ഡോക്ടർമാരുടെ പക്കലുണ്ട്. വിളിക്കുന്നത് വരെ കാത്തിരിക്കുക; '
      'പരിശോധനയ്ക്ക് ശേഷം അന്തിമ റിപ്പോർട്ട് ഇവിടെ വരും.';
  @override
  String resultWithDoctor(String doctor) =>
      '$doctor ഇപ്പോൾ നിങ്ങളെ പരിശോധിക്കുന്നു. പൂർത്തിയാകുമ്പോൾ റിപ്പോർട്ട് ഇവിടെ വരും.';
  @override
  String get resultNoReview =>
      'നിങ്ങളുടെ റിപ്പോർട്ട് കിയോസ്കിൽ നൽകിയിരുന്നു. പകർപ്പ് വേണമെങ്കിൽ ജീവനക്കാരോട് ചോദിക്കുക.';
  @override
  String get diagnosisLabel => 'രോഗനിർണ്ണയം';
  @override
  String get prescribedLabel => 'നിർദ്ദേശിച്ച മരുന്നുകൾ';
  @override
  String get testsLabel => 'പരിശോധനകൾ';
  @override
  String get followUpLabel => 'തുടർ പരിശോധന';
  @override
  String get signedBy => 'ഒപ്പിട്ടത്';
  @override
  String get registrationLabel => 'രജിസ്ട്രേഷൻ നമ്പർ';
  @override
  String get downloadPrescription => 'കുറിപ്പടി ഡൗൺലോഡ് ചെയ്യുക (PDF)';
  @override
  String get noMedicinePrescribed => 'മരുന്ന് നിർദ്ദേശിച്ചിട്ടില്ല.';
  @override
  String get simulatorTitle => 'ബാൻഡ് സിമുലേറ്റർ';
  @override
  String get simulatorHint =>
      'ഇവിടെ അളവുകൾ സജ്ജമാക്കി താഴെ "അളക്കാൻ തുടങ്ങുക" അമർത്തുക.';
  @override
  String get systolic => 'രക്തസമ്മർദ്ദം (മുകളിലെ)';
  @override
  String get diastolic => 'രക്തസമ്മർദ്ദം (താഴത്തെ)';
  @override
  String get pause => 'നിർത്തിവയ്ക്കുക';
  @override
  String get notedSoFar => 'ഡോക്ടർ മെഡോറ രേഖപ്പെടുത്തിയത്';
  @override
  String get yourProblem => 'നിങ്ങളുടെ പ്രശ്നം';
  @override
  String get resume => 'തുടരുക';
  @override
  String get paused => 'നിർത്തിവച്ചിരിക്കുന്നു';
  @override
  String get pausedDetail => 'മൈക്ക് ഓഫാണ്. തയ്യാറാകുമ്പോൾ "തുടരുക" അമർത്തുക.';

  @override
  String get formTitle => 'നിങ്ങളെക്കുറിച്ച് പറയൂ';
  @override
  String get formSubtitle =>
      'മൂന്ന് ചെറിയ ഘട്ടങ്ങൾ, കൂടുതലും തൊട്ടാൽ മതി. ഏകദേശം ഒരു മിനിറ്റ് മതി.';
  @override
  String stepOf(int n, int total) => 'ഘട്ടം $n / $total';
  @override
  String get aboutYou => 'നിങ്ങളെക്കുറിച്ച്';
  @override
  String get aboutYouSubtitle => 'റിപ്പോർട്ട് ആരുടേതാണെന്ന് ഡോക്ടർക്ക് അറിയാൻ.';
  @override
  String get fullName => 'മുഴുവൻ പേര്';
  @override
  String get age => 'വയസ്സ്';
  @override
  String get phone => 'ഫോൺ നമ്പർ';
  @override
  String get gender => 'ലിംഗം';
  @override
  String genderName(String gender) => switch (gender) {
    'male' => 'പുരുഷൻ',
    'female' => 'സ്ത്രീ',
    _ => 'മറ്റുള്ളവർ',
  };
  @override
  String get emailOptional => 'ഇമെയിൽ (നിർബന്ധമില്ല)';
  @override
  String get bothering => 'എന്താണ് ബുദ്ധിമുട്ട്?';
  @override
  String get botheringSubtitle =>
      'അനുഭവപ്പെടുന്നതെല്ലാം തൊട്ട് തിരഞ്ഞെടുക്കുക, വേണമെങ്കിൽ കൂടുതൽ എഴുതുക.';
  @override
  String get feelingLabel => 'എന്താണ് അനുഭവപ്പെടുന്നത്?';
  @override
  String get feelingHint =>
      'മുകളിൽ തൊടുക, അല്ലെങ്കിൽ സ്വന്തം വാക്കുകളിൽ എഴുതുക';
  @override
  String get sinceWhen => 'എപ്പോൾ മുതൽ?';
  @override
  String get durationLabel => 'എത്ര നാളായി ഉണ്ട്?';
  @override
  String get durationHint => 'ഉദാഹരണം: 3 ദിവസം';
  @override
  String get medication => 'മരുന്നും അലർജിയും';
  @override
  String get medicationSubtitle =>
      'ഇതിനായി ഇതിനകം കഴിച്ച മരുന്നുകളും അലർജികളും.';
  @override
  String get medicationLabel => 'ഇതിനായി എന്തെങ്കിലും മരുന്ന് കഴിച്ചോ?';
  @override
  String get medicationHint => 'മുകളിൽ തൊടുക, അല്ലെങ്കിൽ പേര് എഴുതുക';
  @override
  String get enterName => 'നിങ്ങളുടെ പേര് നൽകുക';
  @override
  String get enterAge => 'നിങ്ങളുടെ വയസ്സ് നൽകുക';
  @override
  String get validAge => 'ശരിയായ വയസ്സ് നൽകുക';
  @override
  String get enterPhone => 'റിപ്പോർട്ടിനായി ഫോൺ നമ്പർ നൽകുക';
  @override
  String get validPhone => '10 അക്ക മൊബൈൽ നമ്പർ നൽകുക';
  @override
  String get validEmail => 'ശരിയായ ഇമെയിൽ നൽകുക, ഉദാ. name@gmail.com';
  @override
  String get validName => 'അക്ഷരങ്ങൾ മാത്രം, അക്കങ്ങൾ പാടില്ല';
  @override
  String get selectGender => 'ലിംഗം തിരഞ്ഞെടുക്കുക';
  @override
  String get describeSymptoms => 'നിങ്ങളുടെ ബുദ്ധിമുട്ടുകൾ എഴുതുക';
  @override
  List<String> get symptomSuggestions => const [
    'പനി',
    'ചുമ',
    'ജലദോഷം / മൂക്കൊലിപ്പ്',
    'തൊണ്ടവേദന',
    'തലവേദന',
    'ശരീരവേദന',
    'വയറുവേദന',
    'ഛർദ്ദി',
    'വയറിളക്കം',
    'നെഞ്ചുവേദന',
    'ശ്വാസംമുട്ടൽ',
    'തലകറക്കം',
    'ക്ഷീണം',
    'തൊലിപ്പുറത്ത് ചൊറിച്ചിൽ / തടിപ്പ്',
    'നടുവേദന / സന്ധിവേദന',
    'മൂത്രമൊഴിക്കുമ്പോൾ നീറ്റൽ',
  ];
  @override
  List<String> get durationSuggestions => const [
    'ഇന്ന് മുതൽ',
    '2-3 ദിവസം',
    'ഏകദേശം ഒരാഴ്ച',
    '2 ആഴ്ച',
    'ഒരു മാസത്തിൽ കൂടുതൽ',
  ];
  @override
  List<String> get medicationSuggestions => const [
    'ഒന്നുമില്ല',
    'പാരസെറ്റമോൾ',
    'ഐബുപ്രോഫെൻ',
    'ചുമ സിറപ്പ്',
    'ഗ്യാസിനുള്ള മരുന്ന്',
    'ആന്റിബയോട്ടിക്',
    'അലർജി ഗുളിക',
    'ഇൻഹേലർ',
  ];

  @override
  String get vitalsTitle => 'നമുക്ക് പരിശോധിക്കാം';
  @override
  String vitalsTakes(int minutes) => minutes <= 1
      ? 'ബാൻഡിന് ഏകദേശം ഒരു മിനിറ്റ് വേണം.'
      : 'ബാൻഡിന് ഏകദേശം $minutes മിനിറ്റ് വേണം.';
  @override
  String get continueToReview => 'ഉറപ്പാക്കാൻ തുടരുക';
  @override
  String vitalName(VitalSign sign) => switch (sign) {
    VitalSign.heartRate => 'ഹൃദയമിടിപ്പ്',
    VitalSign.spo2 => 'ഓക്സിജൻ നില (SpO2)',
    VitalSign.temperature => 'ശരീര താപനില',
    VitalSign.bloodPressure => 'രക്തസമ്മർദ്ദം',
  };
  @override
  String get notMeasured => 'അളന്നില്ല';
  @override
  String get putOnBand => 'ബാൻഡ് ധരിക്കുക';
  @override
  String get wearInstruction =>
      'ബാൻഡ് കൈത്തണ്ടയിൽ, എല്ലിന് തൊട്ടുമുകളിൽ, സെൻസർ തൊലിയിൽ തൊടുന്ന വിധം '
      'മുറുക്കി ധരിക്കുക. എന്നിട്ട് "അളക്കാൻ തുടങ്ങുക" അമർത്തുക.';
  @override
  String get connectingBand => 'ബാൻഡുമായി ബന്ധിപ്പിക്കുന്നു';
  @override
  String get connectingDetail =>
      'ഒരു ജാലകം തുറന്നാൽ, പട്ടികയിൽ ബാൻഡ് തിരഞ്ഞെടുത്ത് Pair അമർത്തുക.';
  @override
  String get preparingBand => 'ബാൻഡ് തയ്യാറാക്കുന്നു';
  @override
  String connectedTo(String device) => '$device-മായി ബന്ധിപ്പിച്ചു.';
  @override
  String measuring(VitalSign sign) => '${vitalName(sign)} അളക്കുന്നു';
  @override
  String get keepStill => 'കൈ അനക്കാതെ വയ്ക്കുക.';
  @override
  String keepStillUpTo(int seconds) =>
      'കൈ അനക്കാതെ വയ്ക്കുക. പരമാവധി $seconds സെക്കൻഡ്.';
  @override
  String get vitalsTaken => 'പരിശോധന പൂർത്തിയായി';
  @override
  String get allReadingsIn => 'എല്ലാ അളവുകളും ലഭിച്ചു.';
  @override
  String couldNotRead(Iterable<VitalSign> missed) =>
      'അളക്കാൻ കഴിഞ്ഞില്ല: ${missed.map(vitalName).join(', ')}.';
  @override
  String get didNotWork => 'അത് ശരിയായില്ല';
  @override
  String get bandStopped => 'ബാൻഡ് പ്രതികരിക്കുന്നില്ല.';
  @override
  String get startMeasuring => 'അളക്കാൻ തുടങ്ങുക';
  @override
  String get vitalsFirst => 'ആദ്യം ബാൻഡ് ഉപയോഗിച്ച് പരിശോധന നടത്തുക.';
  @override
  String get vitalsNeededHere =>
      'നിങ്ങളുടെ പരിശോധന ഇനിയും നടത്തണം. ബാൻഡ് ധരിച്ച് "അളക്കാൻ തുടങ്ങുക" അമർത്തുക.';
  @override
  String get measureAgain => 'വീണ്ടും അളക്കുക';
  @override
  String get continueWithoutVitals => 'പരിശോധന ഇല്ലാതെ തുടരുക';
  @override
  String bandMessage(String english) {
    for (final (start, malayalam) in _bandMessages) {
      if (english.startsWith(start)) return malayalam;
    }
    return english;
  }

  /// The band driver's and the browser layer's messages (by how each
  /// starts), in Malayalam.
  static const _bandMessages = [
    (
      'The band disconnected',
      'ബാൻഡിന്റെ ബന്ധം നഷ്ടപ്പെട്ടു. കിയോസ്കിനടുത്ത് വച്ച് വീണ്ടും ശ്രമിക്കുക.',
    ),
    (
      'The band did not respond',
      'ബാൻഡ് പ്രതികരിച്ചില്ല. ചാർജറിൽ നിന്ന് മാറ്റി, കുറച്ച് നിമിഷം കാത്ത് '
          'വീണ്ടും ശ്രമിക്കുക.',
    ),
    (
      'The band could not take a reading',
      'ബാൻഡിന് അളക്കാൻ കഴിഞ്ഞില്ല. സെൻസർ തൊലിയിൽ തൊടുന്ന വിധം ബാൻഡ് '
          'മുറുക്കി വീണ്ടും ശ്രമിക്കുക.',
    ),
    (
      'No device was chosen',
      'ഒരു ഉപകരണവും തിരഞ്ഞെടുത്തില്ല. പട്ടിക ശൂന്യമായിരുന്നെങ്കിൽ ബാൻഡ് '
          'ഓണാണെന്നും അടുത്തുണ്ടെന്നും ഉറപ്പാക്കുക.',
    ),
    ('Tap the button to connect', 'ബന്ധിപ്പിക്കാൻ ബട്ടൺ അമർത്തുക.'),
    (
      'The device did not answer',
      'ഉപകരണം പ്രതികരിച്ചില്ല. ചാർജ് ഉണ്ടെന്നും അടുത്തുണ്ടെന്നും ഉറപ്പാക്കുക.',
    ),
    ('The device disconnected', 'ഉപകരണത്തിന്റെ ബന്ധം നഷ്ടപ്പെട്ടു.'),
    (
      'Bluetooth is not available',
      'ഇവിടെ ബ്ലൂടൂത്ത് ലഭ്യമല്ല. ദയവായി ജീവനക്കാരുടെ സഹായം തേടുക.',
    ),
    (
      'This browser cannot use Bluetooth',
      'ഈ ബ്രൗസറിന് ബ്ലൂടൂത്ത് ഉപയോഗിക്കാൻ കഴിയില്ല. ദയവായി ജീവനക്കാരുടെ '
          'സഹായം തേടുക.',
    ),
    (
      'Bluetooth needs',
      'ബ്ലൂടൂത്ത് പ്രവർത്തിക്കുന്നില്ല. ദയവായി ജീവനക്കാരുടെ സഹായം തേടുക.',
    ),
    ('No band is set up', 'ഈ കിയോസ്കിൽ ബാൻഡ് സജ്ജീകരിച്ചിട്ടില്ല.'),
  ];

  @override
  String get reviewTitle => 'എല്ലാം ശരിയാണോ?';
  @override
  String get reviewSubtitleBand =>
      'മാറ്റം വരുത്താൻ ഏത് വിവരത്തിലും തൊടുക. ബാൻഡിൽ നിന്നുള്ള അളവുകൾ മാറ്റാൻ '
      'കഴിയില്ല.';
  @override
  String get reviewSubtitle => 'മാറ്റം വരുത്താൻ ഏത് വിവരത്തിലും തൊടുക.';
  @override
  String get missingDetails =>
      'ചില വിവരങ്ങൾ ബാക്കിയുണ്ട്. ദയവായി താഴെ പൂരിപ്പിക്കുക.';
  @override
  String get vitalsNotNeeded =>
      'നിങ്ങൾ പറഞ്ഞ ബുദ്ധിമുട്ടിന് ഈ പരിശോധന ആവശ്യമില്ല.';
  @override
  String get vitalsNotCaptured => 'ബാൻഡിൽ നിന്ന് അളവുകൾ ലഭിച്ചിട്ടില്ല.';
  @override
  String get confirmAndReport => 'ഉറപ്പാക്കി റിപ്പോർട്ട് നേടുക';
  @override
  String get notSaved => 'നിങ്ങളുടെ വിവരങ്ങൾ സേവ് ചെയ്യാനായില്ല.';

  @override
  String get connectingMedora => 'ഡോക്ടർ മെഡോറയുമായി ബന്ധിപ്പിക്കുന്നു';
  @override
  String get takingVitals => 'പരിശോധന നടത്തുന്നു';
  @override
  String get medoraSpeaking => 'ഡോക്ടർ മെഡോറ സംസാരിക്കുന്നു';
  @override
  String get listening => 'ഞാൻ കേൾക്കുന്നു';
  @override
  String get thankYou => 'നന്ദി';
  @override
  String get medoraUnavailable => 'ഡോക്ടർ മെഡോറ ഇപ്പോൾ ലഭ്യമല്ല';
  @override
  String get speakNaturally =>
      'സാധാരണ പോലെ സംസാരിക്കുക. എപ്പോൾ വേണമെങ്കിലും ഇടയ്ക്ക് കയറി പറയാം.';
  @override
  String get voiceUnavailable => 'ശബ്ദ സഹായി ഇപ്പോൾ ലഭ്യമല്ല.';
  @override
  String get toldIsSaved => 'ഇതുവരെ പറഞ്ഞ ഉത്തരങ്ങൾ സേവ് ചെയ്തിട്ടുണ്ട്.';
  @override
  String get canTypeInstead => 'പകരം വിവരങ്ങൾ ടൈപ്പ് ചെയ്യാം.';
  @override
  String get continueWithWhatITold => 'എന്റെ ഉത്തരങ്ങൾ പരിശോധിക്കുക';
  @override
  String get endConversation => 'സംഭാഷണം അവസാനിപ്പിക്കുക';
  @override
  String get typeInstead => 'പകരം ടൈപ്പ് ചെയ്യുക';
  @override
  String get conversationAppears => 'നിങ്ങളുടെ സംഭാഷണം ഇവിടെ കാണാം.';
  @override
  String get you => 'നിങ്ങൾ';
  @override
  String get nameLabel => 'പേര്';
  @override
  String get symptomsLabel => 'ബുദ്ധിമുട്ടുകൾ';
  @override
  String get medicationsLabel => 'മരുന്നുകൾ';

  @override
  String get yourReport => 'നിങ്ങളുടെ റിപ്പോർട്ട്';
  @override
  String get noIntake => 'റിപ്പോർട്ട് തയ്യാറാക്കാൻ ഉറപ്പാക്കിയ വിവരങ്ങൾ ഇല്ല.';
  @override
  String get reportTakesMinute =>
      'ഇതിന് ഏകദേശം ഒരു മിനിറ്റ് എടുക്കും. ദയവായി ഇവിടെ തന്നെ നിൽക്കുക.';
  @override
  String get reportFailed => 'റിപ്പോർട്ട് തയ്യാറാക്കാൻ കഴിഞ്ഞില്ല.';
  @override
  String get summary => 'സംഗ്രഹം';
  @override
  String get yourVitals => 'നിങ്ങളുടെ പരിശോധനാ ഫലം';
  @override
  String get measuredByBand => 'സ്മാർട്ട് ബാൻഡ് ഉപയോഗിച്ച് അളന്നത്.';
  @override
  String normalRange(String range) => 'സാധാരണ: $range';
  @override
  String vitalStatus(String status) => switch (status) {
    'normal' => 'സാധാരണം',
    'low' => 'കുറവ്',
    'high' => 'കൂടുതൽ',
    _ => 'വിലയിരുത്തിയില്ല',
  };
  @override
  String get medicines => 'മരുന്നുകൾ';
  @override
  String get medicinesForDoctor => 'ഡോക്ടർ പരിഗണിച്ചേക്കാവുന്ന മരുന്നുകൾ';
  @override
  String get medicinesDoctorOnly =>
      'ഇവ ഡോക്ടറാണ് തീരുമാനിക്കുക. ഡോക്ടർ പറയുന്നതുവരെ ഒരു മരുന്നും '
      'കഴിക്കുകയോ നിർത്തുകയോ മാറ്റുകയോ ചെയ്യരുത്.';
  @override
  String get doctorGives => 'ഇത് ഡോക്ടറോ നഴ്സോ മാത്രമേ നൽകൂ. സ്വയം എടുക്കരുത്.';
  @override
  String get prescription => 'ഡോക്ടറുടെ കുറിപ്പടി വേണം';
  @override
  String forCondition(String condition) => '$condition-ന്';
  @override
  String forDuration(String duration) => duration;
  @override
  String atMost(String amount) => '24 മണിക്കൂറിൽ പരമാവധി $amount';
  @override
  String get whileYouWait => 'കാത്തിരിക്കുമ്പോൾ';
  @override
  String get lifestyleAdvice => 'ജീവിതശൈലി നിർദ്ദേശങ്ങൾ';
  @override
  String get forDoctorReview => 'ഡോക്ടർക്കുള്ള കുറിപ്പുകൾ (ഇംഗ്ലീഷിൽ)';
  @override
  String get getMyReport => 'റിപ്പോർട്ട് സ്വന്തമാക്കുക';
  @override
  String get textMessage => 'SMS';
  @override
  String get smsNotSetUp => 'SMS സൗകര്യം ഇതുവരെ സജ്ജമല്ല';
  @override
  String get email => 'ഇമെയിൽ';
  @override
  String get emailNotSetUp => 'ഇമെയിൽ സൗകര്യം ഇതുവരെ സജ്ജമല്ല';
  @override
  String get noEmail => 'ഇമെയിൽ വിലാസം നൽകിയിട്ടില്ല';
  @override
  String get downloadPdf => 'PDF ഡൗൺലോഡ് ചെയ്യുക';
  @override
  String get send => 'അയയ്ക്കുക';
  @override
  String get sending => 'അയയ്ക്കുന്നു';
  @override
  String get sendAgain => 'വീണ്ടും അയയ്ക്കുക';
  @override
  String sentBy(String channel) => 'റിപ്പോർട്ട് $channel വഴി അയച്ചു.';
  @override
  String get couldNotOpen => 'റിപ്പോർട്ട് തുറക്കാൻ കഴിഞ്ഞില്ല.';
  @override
  String get noKnowledgeBase =>
      'മെഡിക്കൽ വിവരശേഖരം ഉപയോഗിക്കാതെ തയ്യാറാക്കിയത്.';
  @override
  String urgency(String urgency) => switch (urgency) {
    'routine' => 'സാധാരണ പരിശോധന',
    'soon' => 'വേഗം ഡോക്ടറെ കാണുക',
    'urgent' => 'അടിയന്തരമായി കാണണം',
    _ => 'അത്യാഹിതം: ഉടൻ ജീവനക്കാരെ അറിയിക്കുക',
  };
  @override
  String department(String department) {
    final local = _departments[department];
    return local == null
        ? 'വിഭാഗം: $department'
        : 'വിഭാഗം: $local ($department)';
  }

  static const _departments = {
    'Pediatrics': 'ശിശുരോഗ വിഭാഗം',
    'Cardiology': 'ഹൃദ്രോഗ വിഭാഗം',
    'Dermatology': 'ത്വക്ക് രോഗ വിഭാഗം',
    'Gastroenterology': 'ഉദര-കരൾ രോഗ വിഭാഗം',
    'Neurology': 'നാഡീരോഗ വിഭാഗം',
    'Pulmonology': 'ശ്വാസകോശ രോഗ വിഭാഗം',
    'Nephrology': 'വൃക്കരോഗ വിഭാഗം',
    'Endocrinology': 'ഹോർമോൺ രോഗ വിഭാഗം',
    'Oncology': 'കാൻസർ ചികിത്സാ വിഭാഗം',
    'General Surgery': 'ജനറൽ സർജറി',
    'Orthopedic Surgery': 'അസ്ഥിരോഗ വിഭാഗം',
    'Neurosurgery': 'ന്യൂറോ സർജറി',
    'Ophthalmology': 'നേത്രരോഗ വിഭാഗം',
    'Urology': 'മൂത്രാശയ രോഗ വിഭാഗം',
    'Otolaryngology (ENT)': 'ചെവി, മൂക്ക്, തൊണ്ട വിഭാഗം',
    'Obstetrics & Gynecology': 'സ്ത്രീരോഗ വിഭാഗം',
    'Psychiatry': 'മാനസികാരോഗ്യ വിഭാഗം',
    'Anesthesiology': 'വേദന ചികിത്സാ വിഭാഗം',
    'General OPD': 'ജനറൽ ഒ.പി.',
    'Emergency Department': 'അത്യാഹിത വിഭാഗം',
  };

  @override
  String get possibleConditions => 'സാധ്യമായ രോഗാവസ്ഥകൾ';
  @override
  String get notADiagnosis => 'ഡോക്ടർ ഉറപ്പാക്കേണ്ടവ. ഇത് രോഗനിർണ്ണയമല്ല.';
  @override
  String get reportDisclaimer =>
      'ഇത് ഡോക്ടർ ഉറപ്പാക്കേണ്ട ഒരു സ്വയംപ്രവർത്തിത സംഗ്രഹമാണ്. ഇത് '
      'രോഗനിർണ്ണയമോ കുറിപ്പടിയോ അല്ല.';
  @override
  String likelihood(String likelihood) => switch (likelihood) {
    'high' => 'കൂടുതൽ സാധ്യത',
    'medium' => 'സാധ്യതയുണ്ട്',
    _ => 'സാധ്യത കുറവ്',
  };
  @override
  String get reportInEnglish =>
      'ഇപ്പോൾ ഈ റിപ്പോർട്ട് മലയാളത്തിലാക്കാൻ കഴിഞ്ഞില്ല, അതിനാൽ ഇംഗ്ലീഷിൽ '
      'കാണിക്കുന്നു. ആവശ്യമെങ്കിൽ ജീവനക്കാരുടെ സഹായം തേടുക.';
  @override
  String get patientLabel => 'രോഗി';
  @override
  String get toldUs => 'നിങ്ങൾ പറഞ്ഞത്';
  @override
  String get medicinesTaken => 'ഇതിനകം കഴിച്ച മരുന്നുകൾ';
  @override
  String get howToTake => 'എങ്ങനെ കഴിക്കണം';
  @override
  String get whatFor => 'എന്തിന്';
  @override
  String get cautionLabel => 'ശ്രദ്ധിക്കുക';
  @override
  String formName(String form) => switch (form) {
    'tablet' => 'ഗുളിക',
    'capsule' => 'ക്യാപ്സ്യൂൾ',
    'syrup' || 'suspension' => 'സിറപ്പ്',
    'drops' => 'തുള്ളി മരുന്ന്',
    'inhaler' => 'ഇൻഹേലർ',
    'cream' => 'ക്രീം',
    'gel' => 'ജെൽ',
    'ointment' => 'ഓയിന്റ്മെന്റ്',
    'sachet' => 'സാഷെ',
    'lozenge' => 'ലോസഞ്ച്',
    'spray' => 'സ്പ്രേ',
    _ => form,
  };
  @override
  String vitalLabel(String english) => switch (english) {
    'Heart rate' => 'ഹൃദയമിടിപ്പ്',
    'Oxygen (SpO2)' => 'ഓക്സിജൻ നില (SpO2)',
    'Temperature' => 'ശരീര താപനില',
    'Blood pressure' => 'രക്തസമ്മർദ്ദം',
    _ => english,
  };

  @override
  String specialist(String name) => _departments[name] ?? name;
  @override
  String specialistState(String state) => switch (state) {
    'thinking' => 'പരിശോധിക്കുന്നു…',
    'took_part' => 'അഭിപ്രായം നൽകി',
    'stepped_aside' => 'ഈ വിഭാഗത്തിന്റേതല്ല',
    _ => 'ലഭ്യമല്ല',
  };
  @override
  String get understanding => 'നിങ്ങളുടെ ബുദ്ധിമുട്ടുകൾ മനസ്സിലാക്കുന്നു';
  @override
  String get preparingCase => 'വിദഗ്ദ്ധർക്കായി വിവരങ്ങൾ തയ്യാറാക്കുന്നു.';
  @override
  String screening(int count) => '$count വിഭാഗങ്ങളുമായി ഒത്തുനോക്കുന്നു.';
  @override
  String get checkingKnowledge => 'മെഡിക്കൽ വിവരശേഖരം പരിശോധിക്കുന്നു';
  @override
  String get matchingSymptoms =>
      'നിങ്ങളുടെ ബുദ്ധിമുട്ടുകൾ അറിയപ്പെടുന്ന രോഗാവസ്ഥകളുമായി ഒത്തുനോക്കുന്നു.';
  @override
  String get reviewingCase => 'നിങ്ങളുടെ വിവരങ്ങൾ പരിശോധിക്കുന്നു';
  @override
  String get fewMoments => 'ഇതിന് കുറച്ച് നിമിഷങ്ങൾ എടുക്കും.';
  @override
  String get bringingTogether => 'വിലയിരുത്തൽ ഒരുമിപ്പിക്കുന്നു';
  @override
  String get specialistsReviewing =>
      'വിദഗ്ദ്ധർ നിങ്ങളുടെ വിവരങ്ങൾ പരിശോധിക്കുന്നു';
  @override
  String answered(int done, int total, int aside) =>
      '$total-ൽ $done പേർ അഭിപ്രായം നൽകി'
      '${aside > 0 ? ', $aside പേരുടെ വിഭാഗത്തിൽ പെടുന്നില്ല' : ''}.';
  @override
  String get reachingConclusion => 'വിദഗ്ദ്ധ സംഘം തീരുമാനത്തിലെത്തുന്നു';
  @override
  String tookPart(int count) => '$count വിദഗ്ദ്ധർ പങ്കെടുത്തു.';
  @override
  String get writingReport => 'റിപ്പോർട്ട് തയ്യാറാക്കുന്നു';
  @override
  String get preparingAdvice => 'മരുന്നുകളും നിർദ്ദേശങ്ങളും തയ്യാറാക്കുന്നു.';
  @override
  String get reportReady => 'റിപ്പോർട്ട് തയ്യാറാണ്';
  @override
  String get writingSummary => 'സംഗ്രഹം തയ്യാറാക്കുന്നു';
  @override
  List<String> get reportSteps => const [
    'ബുദ്ധിമുട്ടുകൾ',
    'വിവരശേഖരം',
    'വിദഗ്ദ്ധ സംഘം',
    'നിർദ്ദേശങ്ങൾ',
  ];
}
