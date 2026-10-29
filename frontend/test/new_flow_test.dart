import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:medora/api/api_client.dart';
import 'package:medora/config/app_config.dart';
import 'package:medora/doctor/doctor_screen.dart';
import 'package:medora/hospital/hospital_api.dart';
import 'package:medora/main.dart';
import 'package:medora/models/intake.dart';
import 'package:medora/state/service_status.dart';
import 'package:medora/theme/medora_theme.dart';

http.Response json(Object body, [int status = 200]) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

/// The kiosk app against a pretend server [route].
Future<List<http.Request>> pumpKiosk(
  WidgetTester tester,
  String location,
  http.Response Function(http.Request) route, {
  AppConfig config = const AppConfig(),
}) async {
  tester.view.physicalSize = const Size(1280, 4400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final requests = <http.Request>[];
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        appConfigProvider.overrideWithValue(config),
        serviceStatusProvider.overrideWith(
          (ref) => Stream.value(const ServiceStatus()),
        ),
        apiClientProvider.overrideWithValue(
          ApiClient(
            client: MockClient((r) async {
              requests.add(r);
              return route(r);
            }),
          ),
        ),
      ],
      child: MedoraApp(initialLocation: location),
    ),
  );
  await tester.pump();
  return requests;
}

const intake = {
  'name': 'Asha Rao',
  'age': 34,
  'gender': 'female',
  'phone': '9876543210',
  'symptoms': 'fever, cough',
  'duration': '2 days',
  'medications': '',
  'allergies': 'penicillin',
  'language': 'en',
};

void main() {
  testWidgets(
    'the kiosk shows a QR code and carries on when the phone sends the details',
    (tester) async {
      var submitted = false;
      final requests = await pumpKiosk(tester, '/kiosk/phone', (r) {
        final path = r.url.path;
        return switch ((r.method, path)) {
          ('POST', '/api/handoffs') => json({'code': 'abc123code'}, 201),
          ('GET', '/api/handoffs/abc123code') => json(
            submitted
                ? {'status': 'submitted', 'intake': intake}
                : {'status': 'open', 'intake': null},
          ),
          ('POST', '/api/intake/vitals-check') => json({
            'needed': false,
            'reason': 'Not needed.',
          }),
          ('POST', '/api/sessions') => json({'id': 's1'}, 201),
          ('POST', '/api/handoffs/abc123code/done') => http.Response('', 204),
          _ => json({'detail': 'Not found'}, 404),
        };
      });
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const Key('handoff-qr')), findsOneWidget);
      expect(find.text('Waiting for your phone…'), findsOneWidget);

      submitted = true;
      await tester.pump(const Duration(seconds: 3));
      for (var i = 0; i < 6; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      // Saved straight from the phone's details, then the phone is told.
      final saved = requests.singleWhere((r) => r.url.path == '/api/sessions');
      final body = jsonDecode(saved.body) as Map<String, dynamic>;
      expect(body['mode'], 'phone');
      expect(body['allergies'], 'penicillin');
      expect(
        requests.any((r) => r.url.path == '/api/handoffs/abc123code/done'),
        isTrue,
      );
      // The report screen is up; let its one quiet retry run out.
      await tester.pump(const Duration(seconds: 5));
    },
  );

  testWidgets('the phone fills the form and then follows the visit', (
    tester,
  ) async {
    var sessionId = '';
    final requests = await pumpKiosk(tester, '/phone/abc123code', (r) {
      return switch ((r.method, r.url.path)) {
        ('GET', '/api/handoffs/abc123code/phone') => json({
          'status': sessionId.isEmpty && !r.url.path.contains('x')
              ? 'open'
              : 'done',
          'language': 'en',
          'hospital': 'City Hospital',
          'sessionId': sessionId.isEmpty ? null : sessionId,
        }),
        ('POST', '/api/handoffs/abc123code/phone/patients') => json([
          {'id': 'p1', 'label': 'Asha Rao', 'age': 34},
        ]),
        ('POST', '/api/handoffs/abc123code/phone') => http.Response('', 204),
        _ => json({'detail': 'Not found'}, 404),
      };
    });
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('City Hospital'), findsOneWidget);
    expect(find.text('Have you visited this hospital before?'), findsOneWidget);

    // A returning patient types an earlier visit number and picks
    // themselves by full name.
    await tester.enterText(find.byKey(const Key('visited-number')), 'AB1');
    await tester.tap(find.byKey(const Key('visited-find')));
    await tester.pump();
    expect(find.textContaining('6 letters and numbers'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('visited-number')), 'ab12-cd');
    await tester.tap(find.byKey(const Key('visited-find')));
    await tester.pump(const Duration(milliseconds: 100));
    final lookup = requests.lastWhere(
      (r) => r.url.path == '/api/handoffs/abc123code/phone/patients',
    );
    expect(jsonDecode(lookup.body), {'visit': 'ab12cd'});
    expect(find.text('Asha Rao, 34'), findsOneWidget);
    await tester.tap(find.byKey(const Key('visited-p1')));
    await tester.pump();
    expect(find.textContaining('Welcome back'), findsOneWidget);

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
    await tester.tap(find.text('Fever').first);
    await tester.tap(find.text('Diabetes'));
    await tester.pump();
    await tester.tap(find.text('Send to the kiosk'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    final sent =
        jsonDecode(
              requests
                  .singleWhere(
                    (r) =>
                        r.method == 'POST' &&
                        r.url.path == '/api/handoffs/abc123code/phone',
                  )
                  .body,
            )
            as Map<String, dynamic>;
    expect(sent['patientId'], 'p1');
    expect(sent['chronicConditions'], 'Diabetes');
    expect(find.text('Sent. Go back to the kiosk.'), findsOneWidget);

    sessionId = 's1';
    await tester.pump(const Duration(seconds: 4));
    expect(find.byKey(const Key('phone-open-report')), findsOneWidget);
  });

  testWidgets(
    'the patient page waits, then shows the doctor\'s signed report',
    (tester) async {
      var signed = false;
      await pumpKiosk(tester, '/r/s1', (r) {
        if (r.url.path != '/api/sessions/s1/final') return json({}, 404);
        return json({
          'status': signed ? 'final' : 'waiting',
          'visitNumber': 'S1ABCD',
          'name': 'Asha',
          'doctor': 'Dr. Anita Nair',
          'final': signed
              ? {
                  'view': {
                    'patient': {
                      'name': 'Asha Rao',
                      'age': 34,
                      'gender': 'female',
                      'phone': '9876543210',
                    },
                    'conditions': [
                      {
                        'name': {'en': 'Viral fever', 'ml': 'വൈറൽ പനി'},
                        'likelihood': 'high',
                      },
                    ],
                    'medicines': [
                      {
                        'name': 'Paracetamol',
                        'form': 'tablet',
                        'strength': '500 mg',
                        'howToTake': {
                          'en': '1 tablet, every 6 hours.',
                          'ml': '1 ഗുളിക, ഓരോ 6 മണിക്കൂറിലും.',
                        },
                      },
                    ],
                    'tests': [
                      {'en': 'Dengue test', 'ml': 'ഡെങ്കി പരിശോധന'},
                    ],
                    'precautions': [],
                    'followUp': {
                      'en': 'Come back in 3 days.',
                      'ml': '3 ദിവസത്തിനുള്ളിൽ വരിക.',
                    },
                    'vitals': [],
                    'bilingual': true,
                  },
                  'doctor': {
                    'name': 'Dr. Anita Nair',
                    'qualification': 'MBBS, MD',
                    'registrationNumber': 'KMC-12345',
                  },
                  'hospital': {'name': 'City Hospital'},
                  'visitNumber': 'S1ABCD',
                }
              : null,
        });
      });
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('Your visit, Asha'), findsOneWidget);
      expect(
        find.textContaining('Your details are with the doctors'),
        findsOneWidget,
      );

      signed = true;
      await tester.pump(const Duration(seconds: 11));
      await tester.pump(const Duration(milliseconds: 100));
      // An English visit: the signed report in English only.
      expect(find.text('Viral fever'), findsOneWidget);
      expect(find.text('വൈറൽ പനി'), findsNothing);
      expect(find.text('Paracetamol 500 mg'), findsOneWidget);
      expect(find.text('1 tablet, every 6 hours.'), findsOneWidget);
      expect(find.text('Dr. Anita Nair'), findsOneWidget);
      expect(find.textContaining('KMC-12345'), findsOneWidget);
      expect(find.byKey(const Key('download-prescription')), findsOneWidget);
    },
  );

  testWidgets('a doctor takes a patient, sees Medora\'s report and signs', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1600, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final requests = <http.Request>[];
    var picked = false;
    final client = HospitalClient(
      client: MockClient((r) async {
        requests.add(r);
        return switch ((r.method, r.url.path)) {
          ('POST', '/api/hospital/auth/login') => json({
            'user': {
              'id': 'd1',
              'name': 'Dr. Anita Nair',
              'role': 'doctor',
              'mustChangePassword': false,
            },
            'token': 'tok',
            'hospital': {'id': 't1', 'name': 'City Hospital', 'logo': ''},
          }),
          ('GET', '/api/doctor/queue') => json({
            'department': '',
            'doneToday': 0,
            'patients': [
              {
                'id': 'v1',
                'visitNumber': 'V1ABCD',
                'name': 'Asha Rao',
                'age': 34,
                'gender': 'female',
                'symptoms': 'fever, cough',
                'urgency': 'urgent',
                'department': 'General OPD',
                'waitingMinutes': 12,
                'abnormalVitals': 1,
                'returning': true,
                'status': picked ? 'in_consultation' : 'waiting',
                'mine': picked,
                'withDoctor': '',
              },
            ],
          }),
          ('POST', '/api/doctor/visits/v1/pick') => () {
            picked = true;
            return json({'status': 'in_consultation'});
          }(),
          ('GET', '/api/doctor/visits/v1') => json({
            'id': 'v1',
            'visitNumber': 'V1ABCD',
            'patient': {
              'name': 'Asha Rao',
              'age': 34,
              'gender': 'female',
              'phone': '9876543210',
            },
            'told': {
              'symptoms': 'fever, cough',
              'allergies': 'penicillin',
              'pregnancy': '',
            },
            'ai': {
              'urgency': 'urgent',
              'department': 'General OPD',
              'vitals': [],
              'clinicalSummary': 'Two days of fever and cough.',
              'conditions': [
                {
                  'name': 'Viral fever',
                  'probability': 62,
                  'reasoning': 'Short fever.',
                },
                {
                  'name': 'Typhoid',
                  'probability': 6,
                  'doubtReason': 'Fever for only 2 days.',
                },
              ],
              'medicines': [
                {
                  'name': 'Paracetamol',
                  'dose': '500 mg',
                  'frequency': 'every 6 hours',
                  'doseEvidence': {
                    'found': true,
                    'source': '[S1] NFI 2011, page 45',
                  },
                },
              ],
              'doctorNotes': ['Check the throat'],
              'guidelineEvidence': [
                {
                  'label': 'S1',
                  'sourceTitle': 'National Formulary of India',
                  'page': 45,
                  'breadcrumb': 'NFI 2011 › Analgesics › Paracetamol',
                  'excerpt': 'Dose: Oral Adult- 0.5 to 1g every 4 to 6 h',
                  'productionAllowed': false,
                },
              ],
            },
            'history': [],
            'record': {'visits': 2},
            'review': {
              'status': 'in_consultation',
              'diagnosis': [],
              'medicines': [
                {
                  'name': 'Paracetamol',
                  'dose': '500 mg',
                  'frequency': 'every 6 hours',
                  'fromAi': true,
                },
              ],
              'tests': [],
              'advice': ['Drink fluids'],
              'followUp': '',
              'privateNotes': '',
            },
          }),
          ('POST', '/api/doctor/visits/v1/finalize') => json({
            'status': 'final',
          }),
          ('GET', '/api/doctor/suggest') => json(
            switch (r.url.queryParameters['kind']) {
              'medicine' => [
                {
                  'label': 'Dolo 650 · Paracetamol 650 mg tablet',
                  'name': 'Paracetamol',
                  'form': 'tablet',
                  'strength': '650 mg',
                  'route': 'oral',
                  'source': 'brand',
                },
              ],
              'diagnosis' => [
                {'label': 'Viral fever', 'name': 'Viral fever'},
                {'label': 'Viral pneumonia', 'name': 'Viral pneumonia'},
              ],
              _ => [],
            },
          ),
          _ => json({'detail': 'Not found'}, 404),
        };
      }),
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [hospitalClientProvider.overrideWithValue(client)],
        child: MaterialApp(
          theme: MedoraTheme.light(),
          home: const DoctorScreen(),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('Doctor portal'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('hospital-email')),
      'dr@city.in',
    );
    await tester.enterText(
      find.byKey(const Key('hospital-password')),
      'secret123',
    );
    await tester.tap(find.byKey(const Key('hospital-sign-in')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Patient queue'), findsWidgets);
    expect(find.text('V1ABCD'), findsOneWidget);
    expect(find.text('1 vitals out of range'), findsOneWidget);
    await tester.tap(find.byKey(const Key('take-v1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // One column of rows, each showing its gist; the allergy stands out.
    expect(find.byKey(const Key('fold-details')), findsOneWidget);
    expect(find.text('penicillin'), findsOneWidget);
    expect(find.textContaining('Viral fever 62%'), findsOneWidget);
    expect(find.text('62%'), findsNothing); // closed until tapped
    // Medora's doctor report: AI percentages, and the doubted condition with why.
    await tester.tap(find.byKey(const Key('fold-assessment')));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('62%'), findsOneWidget);
    expect(
      find.textContaining('Doubted by Medora\'s check: Fever for only 2 days.'),
      findsOneWidget,
    );
    // The dose check stays; the guideline passages are no longer shown.
    expect(find.text('Dose in NFI 2011, page 45'), findsOneWidget);
    expect(find.byKey(const ValueKey('guideline-sources')), findsNothing);
    expect(find.text('Testing only'), findsNothing);
    expect(find.text('Medora suggested'), findsOneWidget);

    // Nothing to sign without a diagnosis.
    FilledButton sign() =>
        tester.widget<FilledButton>(find.byKey(const Key('finalize')));
    expect(sign().onPressed, isNull);
    expect(find.text('Add a diagnosis'), findsOneWidget);

    // The diagnosis is searched like a search box.
    await tester.enterText(find.byKey(const Key('diagnosis-input')), 'vir');
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Viral pneumonia'), findsOneWidget);
    await tester.tap(find.text('Viral fever').last);
    await tester.pump();
    expect(find.widgetWithText(InputChip, 'Viral fever'), findsOneWidget);
    expect(sign().onPressed, isNotNull);

    // A brand name finds the medicine and fills in its strength and form.
    await tester.ensureVisible(find.byKey(const Key('add-medicine')));
    await tester.tap(find.byKey(const Key('add-medicine')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('med-name-1')), 'dolo');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('Dolo 650 · Paracetamol 650 mg tablet'));
    await tester.pump();
    expect(find.widgetWithText(TextField, '650 mg'), findsOneWidget);
    // Without a dose and how often it cannot be signed.
    expect(find.text('Paracetamol: dose'), findsOneWidget);
    expect(sign().onPressed, isNull);
    // (the second medicine card's Remove; advice lines have one too)
    await tester.tap(find.byTooltip('Remove').at(1));
    await tester.pump();
    expect(sign().onPressed, isNotNull);

    // The signed report is in English unless the doctor switches it.
    await tester.ensureVisible(find.byKey(const Key('report-language-ml')));
    await tester.tap(find.byKey(const Key('report-language-ml')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('finalize')));
    await tester.tap(find.byKey(const Key('finalize')));
    await tester.pump();
    expect(find.textContaining('final report in Malayalam'), findsOneWidget);
    await tester.tap(find.byKey(const Key('confirm-finalize')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    final body =
        jsonDecode(
              requests
                  .singleWhere(
                    (r) => r.url.path == '/api/doctor/visits/v1/finalize',
                  )
                  .body,
            )
            as Map<String, dynamic>;
    expect(body['diagnosis'], [
      {'name': 'Viral fever'},
    ]);
    expect((body['medicines'] as List).single['name'], 'Paracetamol');
    expect(body['advice'], ['Drink fluids']);
    expect(body['language'], 'ml');
    expect(find.text('Signed and sent'), findsOneWidget);
    expect(requests.first.headers['X-Hospital-Token'], isNull);
    expect(requests.last.headers['X-Hospital-Token'], 'tok');
  });

  test('a phone-filled intake comes back whole', () {
    final p = PatientIntake.fromJson({
      ...intake,
      'chronicConditions': 'diabetes',
      'weightKg': 62.5,
      'patientId': 'p1',
    });
    expect(p.gender, Gender.female);
    expect(p.conditions, 'diabetes');
    expect(p.toJson()['weightKg'], 62.5);
    expect(p.toJson()['patientId'], 'p1');
  });
}
