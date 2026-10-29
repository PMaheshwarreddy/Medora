import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:medora/api/api_client.dart';
import 'package:medora/config/app_config.dart';
import 'package:medora/l10n/strings.dart';
import 'package:medora/main.dart';
import 'package:medora/models/intake.dart';
import 'package:medora/state/service_status.dart';
import 'package:medora/widgets/suggestion_terms.dart';

/// The kiosk with a server that records what it is sent.
Future<List<http.Request>> pumpKiosk(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1280, 4400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final requests = <http.Request>[];
  final client = MockClient((request) async {
    requests.add(request);
    return http.Response(
      jsonEncode(
        request.url.path == '/api/intake/vitals-check'
            ? {'needed': false, 'reason': 'ഈ പരിശോധന ആവശ്യമില്ല.'}
            : {},
      ),
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  });
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        appConfigProvider.overrideWithValue(const AppConfig()),
        serviceStatusProvider.overrideWith(
          (ref) => Stream.value(const ServiceStatus()),
        ),
        apiClientProvider.overrideWithValue(ApiClient(client: client)),
      ],
      child: const MedoraApp(initialLocation: '/kiosk'),
    ),
  );
  await tester.pump();
  return requests;
}

void main() {
  test('every Malayalam list matches its English one', () {
    const en = En();
    const ml = Ml();
    expect(ml.symptomSuggestions.length, en.symptomSuggestions.length);
    expect(ml.durationSuggestions.length, en.durationSuggestions.length);
    expect(ml.medicationSuggestions.length, en.medicationSuggestions.length);
    expect(ml.reportSteps.length, en.reportSteps.length);
    // Every department the report can name has a Malayalam name.
    for (final d in [
      'Pediatrics', 'Cardiology', 'Dermatology', 'Gastroenterology',
      'Neurology', 'Pulmonology', 'Nephrology', 'Endocrinology', 'Oncology',
      'General Surgery', 'Orthopedic Surgery', 'Neurosurgery',
      'Ophthalmology', 'Urology', 'Otolaryngology (ENT)',
      'Obstetrics & Gynecology', 'Psychiatry', 'Anesthesiology',
      'General OPD', 'Emergency Department', //
    ]) {
      expect(ml.specialist(d), isNot(d), reason: d);
    }
  });

  test('every chip has its words to recognise, in both languages', () {
    for (final S lang in const [En(), Ml()]) {
      expect(symptomTerms.length, lang.symptomSuggestions.length);
      expect(medicationTerms.length, lang.medicationSuggestions.length);
      expect(allergyTerms.length, lang.allergySuggestions.length);
    }
    // Spoken Malayalam lights up the chip in either language.
    expect(mentions('പനിയും ശരീരവേദനയും', symptomTerms[0]), isTrue);
    expect(mentions('പനിയും ശരീരവേദനയും', symptomTerms[5]), isTrue);
    expect(mentions('ഡോളോ 650', medicationTerms[1]), isTrue);
    expect(mentions('phenomenon', medicationTerms[4]), isFalse);
  });

  testWidgets('the patient can switch the kiosk to Malayalam', (tester) async {
    await pumpKiosk(tester);
    expect(find.text('Speak'), findsOneWidget);

    await tester.tap(find.byKey(const Key('language-toggle')));
    await tester.pump();
    expect(find.text('സംസാരിക്കുക'), findsOneWidget);
    expect(find.text('Speak'), findsNothing);

    await tester.tap(find.byKey(const Key('language-toggle')));
    await tester.pump();
    expect(find.text('Speak'), findsOneWidget);
  });

  testWidgets('a Malayalam visit is sent to the server as Malayalam', (
    tester,
  ) async {
    final requests = await pumpKiosk(tester);
    await tester.tap(find.byKey(const Key('language-toggle')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('mode-manual')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('നിങ്ങളെക്കുറിച്ച് പറയൂ'), findsOneWidget);

    // Required fields are explained in Malayalam.
    await tester.tap(find.text('തുടരുക'));
    await tester.pump();
    expect(find.text('നിങ്ങളുടെ പേര് നൽകുക'), findsOneWidget);

    await tester.enterText(
      find.widgetWithText(TextFormField, 'മുഴുവൻ പേര്'),
      'Anu',
    );
    await tester.enterText(find.widgetWithText(TextFormField, 'വയസ്സ്'), '30');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'ഫോൺ നമ്പർ'),
      '9876543210',
    );
    await tester.tap(find.text('സ്ത്രീ'));
    // A tapped suggestion puts the Malayalam words in the field.
    await tester.tap(find.text('പനി'));
    await tester.pump();
    final symptoms = tester
        .widget<TextFormField>(
          find.widgetWithText(TextFormField, 'എന്താണ് അനുഭവപ്പെടുന്നത്?'),
        )
        .controller!
        .text;
    expect(symptoms, 'പനി');

    await tester.tap(find.text('തുടരുക'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    final check = requests.singleWhere(
      (r) => r.url.path == '/api/intake/vitals-check',
    );
    expect(jsonDecode(check.body), {
      'symptoms': 'പനി',
      'age': 30,
      'duration': '',
      'language': 'ml',
    });
    // The server's reason, already in Malayalam, is shown on review.
    expect(find.text('എല്ലാം ശരിയാണോ?'), findsOneWidget);
    expect(find.text('ഈ പരിശോധന ആവശ്യമില്ല.'), findsOneWidget);
  });
}
