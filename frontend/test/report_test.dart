import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:medora/api/api_client.dart';
import 'package:medora/l10n/strings.dart';
import 'package:medora/models/intake.dart';
import 'package:medora/screens/report_screen.dart';
import 'package:medora/state/intake_controller.dart';
import 'package:medora/state/service_status.dart';
import 'package:medora/theme/medora_theme.dart';

const report = {
  'urgency': 'urgent',
  'department': 'General OPD',
  'summary': 'Fever and cough for two days.',
  'precautions': ['Drink plenty of fluids'],
  'precautionsSource': 'knowledge_base',
  'doctorNotes': ['Check the throat'],
  'vitalFlags': ['Fever (38.4 °C)'],
  'vitalsAssessment': [
    {
      'name': 'Heart rate',
      'value': '73 bpm',
      'normal': '60–100 bpm',
      'status': 'normal',
      'note': '',
    },
    {
      'name': 'Temperature',
      'value': '38.4 °C',
      'normal': '36.1–37.2 °C',
      'status': 'high',
      'note': 'Fever.',
    },
  ],
  'possibleConditions': [
    {
      'name': 'Influenza',
      'likelihood': 'high',
      'reasoning': 'Fever, cough and body aches together.',
      'raisedBy': 'Pulmonology',
      'inKnowledgeBase': true,
      'evidenceScore': 0.72,
      'matchedSymptoms': ['Fever', 'Cough'],
    },
  ],
  'medicines': [
    {
      'name': 'Paracetamol',
      'purpose': 'Brings the fever down.',
      'forCondition': 'Influenza',
      'dose': '500 mg',
      'route': 'oral',
      'frequency': 'every 6 hours as needed',
      'duration': '3 days',
      'maxDaily': '4 g',
      'caution': 'Count doses already taken.',
      'prescription': false,
      'source': 'suggested',
    },
  ],
  'lifestyleAdvice': ['Rest at home for a few days'],
  'panel': [
    {
      'specialist': 'Pulmonology',
      'relevant': true,
      'assessment': 'A viral illness is most likely.',
      'urgency': 'soon',
    },
    {
      'specialist': 'Otolaryngology (ENT)',
      'relevant': true,
      'assessment': 'Consistent with seasonal influenza.',
      'urgency': 'soon',
    },
    {
      'specialist': 'Cardiology',
      'relevant': false,
      'assessment': 'Not a cardiac presentation.',
      'urgency': 'routine',
    },
  ],
  'discussion': 'Both specialists agreed on a viral respiratory infection.',
  'panelNote': '',
  'vitalsMeasured': true,
  'knowledgeUsed': false,
  'generator': 'fake',
  'disclaimer': 'Not a diagnosis.',
  'language': 'ml',
  // The patient's copy (backend patient_view.py).
  'patientView': {
    'patient': {
      'name': 'Asha Rao',
      'age': 34,
      'gender': 'female',
      'phone': '9876543210',
    },
    'summary': {
      'en': 'You have had a fever and cough for two days.',
      'ml': 'രണ്ട് ദിവസമായി പനിയും ചുമയും ഉണ്ട്.',
    },
    'symptoms': {'en': 'fever, cough', 'ml': 'പനി, ചുമ'},
    'duration': {'en': 'two days', 'ml': 'രണ്ട് ദിവസം'},
    'medicationsTaken': {'en': 'none', 'ml': 'ഒന്നുമില്ല'},
    'allergies': {'en': 'penicillin', 'ml': 'penicillin'},
    'conditions': [
      {
        'name': {'en': 'Flu', 'ml': 'ഇൻഫ്ലുവൻസ'},
        'about': {
          'en': 'A common illness caused by a virus.',
          'ml': 'ഒരു വൈറസ് മൂലമുള്ള സാധാരണ അസുഖം.',
        },
        'likelihood': 'high',
      },
    ],
    'medicines': [
      {
        'name': 'Paracetamol',
        'form': 'tablet',
        'strength': '500 mg',
        'prescription': false,
        'howToTake': {
          'en': '500 mg, every 6 hours as needed, for 3 days.',
          'ml': '500 mg, ആവശ്യമെങ്കിൽ ഓരോ 6 മണിക്കൂറിലും, 3 ദിവസത്തേക്ക്.',
        },
        'purpose': {'en': 'Brings the fever down.', 'ml': 'പനി കുറയ്ക്കാൻ.'},
        'caution': {
          'en': 'Count doses already taken.',
          'ml': 'ഇതിനകം കഴിച്ചതും കണക്കാക്കുക.',
        },
      },
    ],
    'vitals': [
      {
        'name': 'Heart rate',
        'value': '73 bpm',
        'normal': '60–100 bpm',
        'status': 'normal',
        'note': null,
      },
      {
        'name': 'Temperature',
        'value': '38.4 °C',
        'normal': '36.1–37.2 °C',
        'status': 'high',
        'note': {'en': 'You have a fever.', 'ml': 'നിങ്ങൾക്ക് പനിയുണ്ട്.'},
      },
    ],
    'vitalFlags': [],
    'precautions': [
      {'en': 'Drink plenty of fluids', 'ml': 'ധാരാളം വെള്ളം കുടിക്കുക'},
    ],
    'lifestyle': [
      {
        'en': 'Rest at home for a few days',
        'ml': 'കുറച്ച് ദിവസം വീട്ടിൽ വിശ്രമിക്കുക',
      },
    ],
    'medicinesNote': null,
    'note': null,
    'bilingual': true,
  },
};

Future<List<http.Request>> pumpReport(
  WidgetTester tester, {
  required bool reportFails,
  bool sms = false,
  Future<void>? hold,
  Map<String, dynamic>? body,
  AppLanguage language = AppLanguage.english,
}) async {
  tester.view.physicalSize = const Size(1280, 5200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final requests = <http.Request>[];
  final client = MockClient((request) async {
    requests.add(request);
    http.Response json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
    final path = request.url.path;
    if (path == '/api/status') {
      return json({
        'online': true,
        'voice': {'available': true, 'detail': ''},
        'sms': {'available': sms},
        'email': {'available': false},
      });
    }
    if (path == '/api/sessions/s1/report/progress') {
      return json({
        'stage': 'panel',
        'roster': ['Neurology', 'Cardiology', 'Pulmonology'],
        'specialists': [
          {'name': 'Neurology', 'state': 'took_part'},
          {'name': 'Pulmonology', 'state': 'thinking'},
          {'name': 'Cardiology', 'state': 'stepped_aside'},
        ],
      });
    }
    if (path == '/api/sessions/s1/report') {
      if (hold != null) await hold;
      return reportFails
          ? json({'detail': 'The report could not be generated.'}, 503)
          : json(body ?? report);
    }
    if (path == '/api/sessions/s1/report/send') return http.Response('', 204);
    return json({'detail': 'Not found'}, 404);
  });

  final container = ProviderContainer(
    overrides: [
      apiClientProvider.overrideWithValue(ApiClient(client: client)),
      // The top bar polls the live status; a fixed one keeps timers out.
      serviceStatusProvider.overrideWith(
        (ref) => Stream.value(const ServiceStatus()),
      ),
    ],
  );
  addTearDown(container.dispose);
  container.read(languageProvider.notifier).set(language);
  container.read(intakeProvider.notifier)
    ..setPatient(const PatientIntake(name: 'Asha Rao', phone: '9876543210'))
    ..setSessionId('s1');

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        theme: MedoraTheme.light(),
        builder: (context, child) => Consumer(
          builder: (context, ref, _) =>
              StringsScope(strings: ref.watch(stringsProvider), child: child!),
        ),
        home: const ReportScreen(),
      ),
    ),
  );
  // The orb animates forever while loading, so settle by pumping time.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pump(const Duration(milliseconds: 100));
  return requests;
}

void main() {
  testWidgets('an English visit gets the report in English only', (
    tester,
  ) async {
    await pumpReport(tester, reportFails: false);

    expect(find.text('Urgent'), findsOneWidget);
    expect(find.text('Department: General OPD'), findsOneWidget);
    // The manager's order: patient, what they told us, vitals, summary,
    // conditions, medicines, precautions.
    expect(find.text('Asha Rao'), findsOneWidget);
    expect(find.text('fever, cough'), findsOneWidget);
    expect(
      find.text('You have had a fever and cough for two days.'),
      findsOneWidget,
    );
    expect(find.text('Normal: 60–100 bpm'), findsOneWidget);
    expect(find.text('You have a fever.'), findsOneWidget);
    expect(find.text('Flu'), findsOneWidget);
    expect(find.text('More likely'), findsOneWidget);
    // Never a percentage on the patient's report.
    expect(find.textContaining('%'), findsNothing);
    // Medicines: name and strength, form, how to take it.
    expect(find.text('Paracetamol 500 mg'), findsOneWidget);
    expect(find.text('tablet'), findsOneWidget);
    expect(
      find.text('500 mg, every 6 hours as needed, for 3 days.'),
      findsOneWidget,
    );
    expect(find.text('Count doses already taken.'), findsOneWidget);
    expect(find.textContaining('The doctor decides on these'), findsOneWidget);
    expect(find.text('Drink plenty of fluids'), findsOneWidget);
    // No Malayalam on an English report (the top bar's language switch
    // still names Malayalam).
    expect(
      find.byWidgetPredicate(
        (w) =>
            w is Text &&
            w.data != 'മലയാളം' &&
            RegExp('[\u0D00-\u0D7F]').hasMatch(w.data ?? ''),
      ),
      findsNothing,
    );
    // The doctor's notes and the panel's discussion are not for the patient.
    expect(find.text('Check the throat'), findsNothing);
    expect(find.text('Consistent with seasonal influenza.'), findsNothing);
    expect(find.textContaining('AI'), findsNothing);
  });

  testWidgets('a Malayalam visit gets the report in Malayalam only', (
    tester,
  ) async {
    final view = Map<String, dynamic>.from(report['patientView'] as Map)
      ..['language'] = 'ml';
    await pumpReport(
      tester,
      reportFails: false,
      body: {...report, 'patientView': view},
    );

    expect(find.text('അടിയന്തരമായി കാണണം'), findsOneWidget);
    expect(find.text('വിഭാഗം: ജനറൽ ഒ.പി. (General OPD)'), findsOneWidget);
    expect(find.text('പനി, ചുമ'), findsOneWidget);
    expect(find.text('രണ്ട് ദിവസമായി പനിയും ചുമയും ഉണ്ട്.'), findsOneWidget);
    expect(find.text('സാധാരണ: 60–100 bpm'), findsOneWidget);
    expect(find.text('ഇൻഫ്ലുവൻസ'), findsOneWidget);
    expect(find.text('ഗുളിക'), findsOneWidget);
    expect(
      find.textContaining('ആവശ്യമെങ്കിൽ ഓരോ 6 മണിക്കൂറിലും'),
      findsOneWidget,
    );
    expect(find.text('ധാരാളം വെള്ളം കുടിക്കുക'), findsOneWidget);
    // The English texts are not shown beside it.
    expect(find.text('Urgent'), findsNothing);
    expect(
      find.text('You have had a fever and cough for two days.'),
      findsNothing,
    );
    expect(find.text('Drink plenty of fluids'), findsNothing);
  });

  testWidgets('a report from before the patient view still shows', (
    tester,
  ) async {
    await pumpReport(
      tester,
      reportFails: false,
      body: {...report, 'patientView': null},
    );
    expect(find.text('Fever and cough for two days.'), findsOneWidget);
    expect(find.text('Drink plenty of fluids'), findsOneWidget);
    expect(find.text('Paracetamol'), findsOneWidget);
    // An English visit: nothing to translate, so no notice.
    expect(find.textContaining('could not be prepared'), findsNothing);
  });

  testWidgets('delivery that is not set up cannot be tapped', (tester) async {
    await pumpReport(tester, reportFails: false);

    expect(find.text('Text messages are not set up yet'), findsOneWidget);
    expect(find.text('Email is not set up yet'), findsOneWidget);
    for (final button in tester.widgetList<OutlinedButton>(
      find.widgetWithText(OutlinedButton, 'Send'),
    )) {
      expect(button.onPressed, isNull);
    }
  });

  testWidgets('sends by text message when it is set up', (tester) async {
    final requests = await pumpReport(tester, reportFails: false, sms: true);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Send').first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(requests.last.url.path, '/api/sessions/s1/report/send');
    expect(jsonDecode(requests.last.body), {'channel': 'sms'});
    expect(find.text('Report sent by text message.'), findsOneWidget);
    expect(find.text('Send again'), findsOneWidget);
  });

  testWidgets('a failed report is retried once, then offers a retry', (
    tester,
  ) async {
    final requests = await pumpReport(tester, reportFails: true);
    // Still working on it: the first failure is retried quietly.
    expect(find.text('The report could not be generated.'), findsNothing);
    await tester.pump(const Duration(seconds: 3));
    await tester.pump(const Duration(milliseconds: 100));

    expect(
      requests.where((r) => r.url.path == '/api/sessions/s1/report').length,
      2,
    );
    expect(find.text('The report could not be generated.'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('while it is made, the specialists actually asked are shown', (
    tester,
  ) async {
    final hold = Completer<void>();
    await pumpReport(tester, reportFails: false, hold: hold.future);
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Specialists are reviewing your case'), findsOneWidget);
    expect(find.text('Pulmonology'), findsOneWidget);
    expect(find.text('reviewing…'), findsOneWidget);
    expect(find.text('Neurology'), findsOneWidget);
    expect(find.text('opinion given'), findsOneWidget);
    expect(find.text('not their field'), findsOneWidget);
    expect(
      find.text(
        '2 of 3 have given their view, 1 found it outside their field.',
      ),
      findsOneWidget,
    );

    hold.complete();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('Specialists are reviewing your case'), findsNothing);
  });
}
