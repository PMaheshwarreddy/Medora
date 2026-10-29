import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:medora/api/api_client.dart';

import 'package:medora/band/band_service.dart';
import 'package:medora/band/ble/ble_central.dart';
import 'package:medora/band/drivers/qring/qring_band.dart';
import 'package:medora/config/app_config.dart';
import 'package:medora/main.dart';
import 'package:medora/models/intake.dart';
import 'package:medora/screens/welcome_screen.dart';
import 'package:medora/state/intake_controller.dart';
import 'package:medora/state/service_status.dart';
import 'package:go_router/go_router.dart';
import 'package:medora/widgets/intake_form.dart';

import 'qring_test.dart' show FakeCentral, FakeRing, fast;

Future<void> pumpApp(
  WidgetTester tester, {
  AppConfig config = const AppConfig(),
  ServiceStatus status = const ServiceStatus(),
  BandService? band,
  String location = '/kiosk',
  Map<String, dynamic>? vitalsCheck,
}) async {
  tester.view.physicalSize = const Size(1280, 4400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        appConfigProvider.overrideWithValue(config),
        serviceStatusProvider.overrideWith((ref) => Stream.value(status)),
        if (band != null) bandServiceProvider.overrideWithValue(band),
        // The server's answer to "does this complaint need vitals?".
        if (vitalsCheck != null)
          apiClientProvider.overrideWithValue(
            ApiClient(
              client: MockClient(
                (request) async =>
                    request.url.path == '/api/intake/vitals-check'
                    ? http.Response(
                        jsonEncode(vitalsCheck),
                        200,
                        headers: {'content-type': 'application/json'},
                      )
                    : http.Response('{}', 404),
              ),
            ),
          ),
      ],
      child: MedoraApp(initialLocation: location),
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets('welcome offers voice and manual intake', (tester) async {
    await pumpApp(tester);

    expect(find.byKey(const Key('mode-voice')), findsOneWidget);
    expect(find.byKey(const Key('mode-manual')), findsOneWidget);
    expect(find.text('Speak'), findsOneWidget);
    expect(find.text('Use my phone'), findsOneWidget);
    expect(find.byKey(const Key('mode-phone')), findsOneWidget);
  });

  testWidgets('manual intake blocks on missing required details', (
    tester,
  ) async {
    await pumpApp(tester);
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    await tester.tap(find.text('Continue'));
    await tester.pump();

    expect(find.text('Enter your name'), findsOneWidget);
    expect(find.text('Select your gender'), findsOneWidget);
    expect(find.text('Describe your symptoms'), findsOneWidget);
    expect(find.text("Let's take your vitals"), findsNothing);
  });

  testWidgets('manual intake reaches vitals, which waits for the band', (
    tester,
  ) async {
    // The real band, on a machine without Bluetooth (the test VM).
    await pumpApp(tester, band: QRingBand(createBleCentral()));
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    await tester.enterText(
      find.widgetWithText(TextFormField, 'Full name'),
      'Asha Rao',
    );
    await tester.enterText(find.widgetWithText(TextFormField, 'Age'), '34');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Phone number'),
      '9876543210',
    );
    await tester.tap(find.text('Female'));
    await tester.enterText(
      find.widgetWithText(TextFormField, 'What are you feeling?'),
      'Headache and fever',
    );
    await tester.pump();
    await tester.tap(find.text('Continue'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text("Let's take your vitals"), findsOneWidget);
    // Tests run without Bluetooth: the kiosk says so and offers a way on.
    expect(find.text('Bluetooth is not available here.'), findsOneWidget);
    expect(find.text('Continue without vitals'), findsOneWidget);
    final next = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Continue to review'),
    );
    expect(next.onPressed, isNull);
  });

  testWidgets('voice switched off leaves only the form', (tester) async {
    await pumpApp(tester, config: const AppConfig(voiceIntake: false));

    expect(find.byKey(const Key('mode-voice')), findsNothing);
    expect(find.byKey(const Key('mode-manual')), findsOneWidget);
  });

  testWidgets('band switched off skips vitals', (tester) async {
    await pumpApp(tester, config: const AppConfig(smartBand: false));
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('Vitals'), findsNothing);
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Full name'),
      'Asha Rao',
    );
    await tester.enterText(find.widgetWithText(TextFormField, 'Age'), '34');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Phone number'),
      '9876543210',
    );
    await tester.tap(find.text('Female'));
    await tester.enterText(
      find.widgetWithText(TextFormField, 'What are you feeling?'),
      'Headache and fever',
    );
    await tester.pump();
    await tester.tap(find.text('Continue'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('Is everything correct?'), findsOneWidget);
    expect(find.text('Heart rate'), findsNothing);
  });

  test('config with both intake modes off falls back to the form', () {
    final config = AppConfig.fromJson({
      'voiceIntake': false,
      'manualIntake': false,
    });
    expect(config.manualIntake, isTrue);
  });

  testWidgets('offline: the form still works, voice waits for internet', (
    tester,
  ) async {
    await pumpApp(
      tester,
      status: const ServiceStatus(
        online: false,
        voice: false,
        voiceDetail: 'The voice agent needs an internet connection.',
      ),
    );

    expect(find.text('Offline mode'), findsOneWidget);
    expect(
      find.textContaining('You can still type your details'),
      findsOneWidget,
    );
    // Voice needs the connection; the phone (over the hospital Wi-Fi) and
    // typing here do not.
    expect(find.text('Needs an internet connection'), findsOneWidget);
    await tester.tap(find.byKey(const Key('mode-voice')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(
      find.byKey(const Key('mode-voice')),
      findsOneWidget,
    ); // did not navigate

    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Tell us about yourself'), findsOneWidget);
  });

  testWidgets('manual intake: suggestions fill the form with one tap', (
    tester,
  ) async {
    await pumpApp(tester);
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump(const Duration(milliseconds: 500));

    String field(String label) => tester
        .widget<TextFormField>(find.widgetWithText(TextFormField, label))
        .controller!
        .text;
    // "None" is offered for medicines and for long-term conditions; the
    // medicines' comes first.
    Future<void> choose(String label) async {
      await tester.ensureVisible(find.text(label).first);
      await tester.tap(find.text(label).first);
      await tester.pump(const Duration(milliseconds: 200));
    }

    await choose('Fever');
    await choose('Cough');
    expect(field('What are you feeling?'), 'Fever, Cough');
    // Tapping again takes it back out.
    await choose('Fever');
    expect(field('What are you feeling?'), 'Cough');

    await choose('About a week');
    expect(field('How long have you had them?'), 'About a week');

    // "None" cannot stand beside a medicine.
    await choose('Paracetamol');
    await choose('Antacid');
    expect(
      field('Have you taken any medication for this?'),
      'Paracetamol, Antacid',
    );
    await choose('None');
    expect(field('Have you taken any medication for this?'), 'None');
    await choose('Ibuprofen');
    expect(field('Have you taken any medication for this?'), 'Ibuprofen');
  });

  testWidgets('vitals: the ring is started with a tap and fills the tiles', (
    tester,
  ) async {
    await pumpApp(
      tester,
      location: '/kiosk/vitals',
      band: QRingBand(
        FakeCentral(FakeRing()),
        timing: fast,
        measures: VitalSign.values,
      ),
    );
    expect(find.text('Put on the band'), findsOneWidget);
    expect(find.textContaining('wrist'), findsOneWidget);
    final next = find.widgetWithText(FilledButton, 'Continue to review');
    expect(tester.widget<FilledButton>(next).onPressed, isNull);

    await tester.tap(find.text('Start measuring'));
    for (var i = 0; i < 60; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }

    expect(find.text('Vitals taken'), findsOneWidget);
    expect(find.text('72'), findsOneWidget);
    expect(find.text('97'), findsOneWidget);
    expect(find.text('118/76'), findsOneWidget);
    expect(find.text('36.8'), findsOneWidget);
    expect(tester.widget<FilledButton>(next).onPressed, isNotNull);
  });

  testWidgets('vitals: only what the band measures is shown', (tester) async {
    await pumpApp(
      tester,
      location: '/kiosk/vitals',
      band: QRingBand(FakeCentral(FakeRing()), timing: fast),
    );
    expect(find.text('Heart rate'), findsOneWidget);
    expect(find.text('Oxygen (SpO2)'), findsOneWidget);
    expect(find.text('Temperature'), findsNothing);
    expect(find.text('Blood pressure'), findsNothing);
    expect(find.text('The band takes about a minute.'), findsOneWidget);
  });

  testWidgets('vitals: a measurement can be cancelled', (tester) async {
    await pumpApp(
      tester,
      location: '/kiosk/vitals',
      band: QRingBand(FakeCentral(FakeRing()), timing: fast),
    );
    await tester.tap(find.text('Start measuring'));
    await tester.pump(const Duration(milliseconds: 10));
    await tester.tap(find.text('Cancel'));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Start measuring'), findsOneWidget);
    expect(find.text('72'), findsNothing);
  });

  testWidgets('a complaint that needs no vitals goes straight to review', (
    tester,
  ) async {
    await pumpApp(
      tester,
      vitalsCheck: {
        'needed': false,
        'reason': 'Your knee pain does not need a heart or oxygen check.',
      },
    );
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Full name'),
      'Asha Rao',
    );
    await tester.enterText(find.widgetWithText(TextFormField, 'Age'), '34');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Phone number'),
      '9876543210',
    );
    await tester.tap(find.text('Female'));
    await tester.enterText(
      find.widgetWithText(TextFormField, 'What are you feeling?'),
      'Pain in my knee after a twist',
    );
    await tester.pump();
    await tester.ensureVisible(find.text('Continue'));
    await tester.tap(find.text('Continue'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text("Let's take your vitals"), findsNothing);
    expect(find.text('Is everything correct?'), findsOneWidget);
    expect(
      find.text('Your knee pain does not need a heart or oxygen check.'),
      findsOneWidget,
    );
    expect(
      find.text('Vitals have not been captured from the band.'),
      findsNothing,
    );
    expect(find.text('Heart rate'), findsNothing);
  });

  testWidgets('a complaint that needs vitals goes to the band', (tester) async {
    await pumpApp(tester, vitalsCheck: {'needed': true, 'reason': ''});
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Full name'),
      'Asha Rao',
    );
    await tester.enterText(find.widgetWithText(TextFormField, 'Age'), '34');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Phone number'),
      '9876543210',
    );
    await tester.tap(find.text('Female'));
    await tester.enterText(
      find.widgetWithText(TextFormField, 'What are you feeling?'),
      'Fever and cough',
    );
    await tester.pump();
    await tester.ensureVisible(find.text('Continue'));
    await tester.tap(find.text('Continue'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text("Let's take your vitals"), findsOneWidget);
  });

  testWidgets('the language is chosen at the front of the welcome page', (
    tester,
  ) async {
    await pumpApp(tester);
    expect(find.text('HOW WOULD YOU LIKE TO START?'), findsOneWidget);
    await tester.tap(find.byKey(const Key('welcome-language-ml')));
    await tester.pump();
    expect(find.text('എങ്ങനെ തുടങ്ങണം?'), findsOneWidget);
    await tester.tap(find.byKey(const Key('welcome-language-en')));
    await tester.pump();
    expect(find.text('HOW WOULD YOU LIKE TO START?'), findsOneWidget);
  });

  testWidgets('the form refuses numbers in a name and a wrong phone or email', (
    tester,
  ) async {
    await pumpApp(tester);
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump(const Duration(milliseconds: 500));
    final name = find.widgetWithText(TextFormField, 'Full name');
    await tester.enterText(name, 'Asha2 Rao');
    // Numbers cannot be typed into a name at all.
    expect(find.text('Asha Rao'), findsOneWidget);
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Phone number'),
      '12345',
    );
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Email (optional)'),
      'asha@gmail',
    );
    await tester.ensureVisible(find.text('Continue'));
    await tester.tap(find.text('Continue'));
    await tester.pump();
    expect(find.text('Enter a 10-digit mobile number'), findsOneWidget);
    expect(find.textContaining('Enter a valid email'), findsOneWidget);
    expect(find.text('Use letters only, no numbers'), findsNothing);

    // +91 and spaces are fine; a single letter is not a name.
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Phone number'),
      '+91 98765 43210',
    );
    await tester.enterText(name, 'A');
    await tester.tap(find.text('Continue'));
    await tester.pump();
    expect(find.text('Enter a 10-digit mobile number'), findsNothing);
    expect(find.text('Use letters only, no numbers'), findsOneWidget);
    expect(indianMobile('098765 43210'), '9876543210');
    expect(indianMobile('5876543210'), isNull);
  });

  testWidgets('vitals missed during the conversation are taken on review', (
    tester,
  ) async {
    await pumpApp(tester);
    final context = tester.element(find.byType(WelcomeScreen));
    final intake = ProviderScope.containerOf(
      context,
    ).read(intakeProvider.notifier);
    intake.start(IntakeMode.voice);
    intake.setPatient(
      const PatientIntake(
        name: 'Asha Rao',
        age: 34,
        gender: Gender.female,
        phone: '9876543210',
        symptoms: 'fever',
      ),
    );
    GoRouter.of(context).go('/kiosk/review');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    // The band (here the simulator) is offered, and confirming waits for it.
    expect(find.byKey(const Key('review-band')), findsOneWidget);
    expect(find.text('Continue without vitals'), findsNothing);
    await tester.ensureVisible(find.text('Confirm and get my report'));
    await tester.tap(find.text('Confirm and get my report'));
    await tester.pump();
    expect(
      find.text('Please take your vitals with the band first.'),
      findsOneWidget,
    );

    await tester.ensureVisible(find.text('Start measuring'));
    await tester.tap(find.text('Start measuring'));
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.byKey(const Key('review-band')), findsNothing);
    expect(find.text('76'), findsWidgets); // the simulator's heart rate
  });

  testWidgets('what the patient said lights up the matching chips', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 4400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    PatientIntake? submitted;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: IntakeForm(
              // As the voice agent hears it, not as the chips write it.
              initial: const PatientIntake(
                symptoms: 'high fever, worse at night, body pains',
                medications: 'Dolo 650',
                allergies: 'allergic to penicillin',
                pregnancy: 'no',
              ),
              submitLabel: 'Go',
              onSubmit: (p) => submitted = p,
            ),
          ),
        ),
      ),
    );

    bool selected(String label) => find
        .descendant(
          of: find.ancestor(
            of: find.text(label),
            matching: find.byType(AnimatedContainer),
          ),
          matching: find.byIcon(Icons.check_circle_rounded),
        )
        .evaluate()
        .isNotEmpty;

    expect(selected('Fever'), isTrue);
    expect(selected('Body pain'), isTrue);
    expect(selected('Headache'), isFalse);
    expect(selected('Paracetamol'), isTrue);
    expect(selected('Penicillin'), isTrue);
    expect(selected('No allergies'), isFalse);
    // The pregnancy answer the agent heard can be corrected here.
    expect(find.text('Could you be pregnant?'), findsOneWidget);
    expect(selected('No'), isTrue);

    // Tapping a lit chip removes what said it, in the patient's words too.
    await tester.tap(find.text('Fever'));
    await tester.pump();
    final symptoms = tester
        .widget<TextFormField>(
          find.widgetWithText(TextFormField, 'What are you feeling?'),
        )
        .controller!
        .text;
    expect(symptoms, 'worse at night, body pains');
    expect(submitted, isNull);
  });
}
