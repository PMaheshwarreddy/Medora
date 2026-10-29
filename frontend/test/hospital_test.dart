import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:medora/hospital/hospital_api.dart';
import 'package:medora/hospital/hospital_screen.dart';
import 'package:medora/theme/medora_theme.dart';

/// A pretend hospital API that records what it is sent.
class FakeHospital {
  FakeHospital({this.role = 'hospital_admin', this.mustChange = false});

  final String role;
  bool mustChange;
  final requests = <http.Request>[];
  final people = <Map<String, dynamic>>[];

  Map<String, dynamic> get user => {
    'id': 'u1',
    'name': 'Meera Admin',
    'email': 'admin@city.in',
    'role': role,
    'mustChangePassword': mustChange,
  };

  static const hospital = {'id': 't1', 'name': 'City Hospital', 'logo': ''};

  late final client = HospitalClient(
    client: MockClient((request) async {
      requests.add(request);
      http.Response json(Object body, [int status = 200]) => http.Response(
        jsonEncode(body),
        status,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
      final path = request.url.path.replaceFirst('/api/hospital', '');
      return switch ((request.method, path)) {
        ('POST', '/auth/login') =>
          jsonDecode(request.body)['password'] == 'right'
              ? json({'user': user, 'token': 't0k3n', 'hospital': hospital})
              : json({'detail': 'Wrong email or password'}, 401),
        ('POST', '/auth/password') => () {
          mustChange = false;
          return http.Response('', 204);
        }(),
        ('GET', '/dashboard') => json({
          'hospital': hospital,
          'today': {
            'visits': 3,
            'reports': 2,
            'urgent': 1,
            'byUrgency': {'routine': 1, 'soon': 0, 'urgent': 1, 'emergency': 0},
            'byDepartment': [
              {'department': 'General OPD', 'visits': 2},
            ],
          },
          'week': [
            for (var i = 0; i < 7; i++)
              {
                'date': DateTime(2026, 10, 16 + i).toUtc().toIso8601String(),
                'visits': i,
              },
          ],
          'recent': [
            {
              'id': 'v1',
              'at': '2026-10-22T05:00:00Z',
              'name': 'Asha Rao',
              'age': 34,
              'urgency': 'urgent',
              'department': 'General OPD',
            },
          ],
          'people': {'doctors': 4, 'staff': 2, 'admins': 1, 'departments': 3},
        }),
        ('GET', '/people') => json(people),
        ('GET', '/departments') => json({
          'departments': [
            {
              'id': 'd1',
              'name': 'Cardiology',
              'reportDepartment': 'Cardiology',
              'active': true,
              'doctors': 0,
            },
          ],
          'reportDepartments': ['Cardiology', 'General OPD'],
        }),
        ('POST', '/people') => () {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          final person = {
            ...body,
            'id': 'p${people.length + 1}',
            'active': true,
            'mustChangePassword': true,
            'department': 'Cardiology',
          };
          people.add(person);
          return json({
            'person': person,
            'temporaryPassword': 'Tmp7Pass9X',
          }, 201);
        }(),
        ('GET', '/visits') => json([
          {
            'id': 'v1',
            'at': '2026-10-22T05:00:00Z',
            'name': 'Asha Rao',
            'age': 34,
            'gender': 'female',
            'phone': '9876543210',
            'symptoms': 'fever, cough',
            'urgency': 'soon',
            'department': 'General OPD',
          },
        ]),
        ('GET', '/visits/v1') => json({
          'id': 'v1',
          'at': '2026-10-22T05:00:00Z',
          'name': 'Asha Rao',
          'age': 34,
          'gender': 'female',
          'phone': '9876543210',
          'symptoms': 'fever, cough',
          'allergies': 'penicillin',
          'urgency': 'soon',
          'department': 'General OPD',
          'report': {
            'department': 'General OPD',
            'clinicalSummary': 'Two days of fever and cough.',
            'possibleConditions': [
              {'name': 'Viral fever', 'likelihood': 'high'},
            ],
            'medicines': [],
            'vitalsAssessment': [],
          },
        }),
        _ => json({'detail': 'Not found'}, 404),
      };
    }),
  );
}

Future<FakeHospital> pumpPortal(
  WidgetTester tester, {
  String role = 'hospital_admin',
  bool mustChange = false,
}) async {
  tester.view.physicalSize = const Size(1400, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final fake = FakeHospital(role: role, mustChange: mustChange);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [hospitalClientProvider.overrideWithValue(fake.client)],
      child: MaterialApp(
        theme: MedoraTheme.light(),
        home: const HospitalScreen(),
      ),
    ),
  );
  await tester.pump();
  return fake;
}

Future<void> signIn(WidgetTester tester, {String password = 'right'}) async {
  await tester.enterText(
    find.byKey(const Key('hospital-email')),
    'admin@city.in',
  );
  await tester.enterText(find.byKey(const Key('hospital-password')), password);
  await tester.tap(find.byKey(const Key('hospital-sign-in')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  testWidgets('a hospital admin signs in and sees today at the hospital', (
    tester,
  ) async {
    final fake = await pumpPortal(tester);
    expect(find.text('Hospital portal'), findsOneWidget);

    await signIn(tester, password: 'wrong');
    expect(find.text('Wrong email or password'), findsOneWidget);

    await signIn(tester);
    expect(find.text('City Hospital'), findsOneWidget);
    expect(find.text('Visits today'), findsOneWidget);
    expect(find.text('3'), findsWidgets);
    expect(find.text('Urgent or emergency'), findsOneWidget);
    expect(find.text('Asha Rao, 34'), findsOneWidget);
    // Every call carries the hospital's own token.
    expect(
      fake.requests
          .where((r) => r.url.path == '/api/hospital/dashboard')
          .single
          .headers['X-Hospital-Token'],
      't0k3n',
    );
  });

  testWidgets('a temporary password must be changed before anything else', (
    tester,
  ) async {
    final fake = await pumpPortal(tester, mustChange: true);
    await signIn(tester);
    expect(find.text('Choose your password'), findsOneWidget);
    expect(find.text('Visits today'), findsNothing);

    await tester.enterText(find.byKey(const Key('password-current')), 'right');
    await tester.enterText(
      find.byKey(const Key('password-new')),
      'long-enough',
    );
    await tester.enterText(
      find.byKey(const Key('password-again')),
      'different',
    );
    await tester.tap(find.byKey(const Key('password-save')));
    await tester.pump();
    expect(
      find.text('The two new passwords are not the same.'),
      findsOneWidget,
    );

    await tester.enterText(
      find.byKey(const Key('password-again')),
      'long-enough',
    );
    await tester.tap(find.byKey(const Key('password-save')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(fake.mustChange, isFalse);
    expect(find.text('Visits today'), findsOneWidget);
  });

  testWidgets('adding a doctor shows the temporary password once', (
    tester,
  ) async {
    final fake = await pumpPortal(tester);
    await signIn(tester);
    await tester.tap(find.byKey(const Key('hnav-doctors')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('0 doctors'), findsOneWidget);

    await tester.tap(find.byKey(const Key('add-doctor')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const Key('person-name')),
      'Dr. Anita Nair',
    );
    await tester.enterText(
      find.byKey(const Key('person-email')),
      'anita@city.in',
    );
    // Without a registration number the form does not submit.
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pump();
    expect(find.text('Enter the registration number'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('person-registration')),
      'KMC-12345',
    );
    await tester.tap(find.byKey(const Key('person-save')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    final sent = jsonDecode(
      fake.requests.lastWhere((r) => r.method == 'POST').body,
    );
    expect(sent['role'], 'doctor');
    expect(sent['registrationNumber'], 'KMC-12345');
    expect(find.text('Temporary password: Tmp7Pass9X'), findsOneWidget);
    await tester.tap(find.text('Done'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Dr. Anita Nair'), findsOneWidget);
    expect(find.text('1 doctors'), findsOneWidget);
  });

  testWidgets('opening a visit shows its report', (tester) async {
    final fake = await pumpPortal(tester);
    await signIn(tester);
    await tester.tap(find.byKey(const Key('hnav-visits')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.text('9876543210'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(fake.requests.last.url.path, '/api/hospital/visits/v1');
    expect(find.text('Two days of fever and cough.'), findsOneWidget);
    expect(find.text('Viral fever (high)'), findsOneWidget);
    expect(find.text('penicillin'), findsOneWidget);
  });

  testWidgets('a doctor cannot use the admin portal', (tester) async {
    await pumpPortal(tester, role: 'doctor');
    await signIn(tester);
    expect(
      find.textContaining('This portal is for the hospital\'s administrators'),
      findsOneWidget,
    );
    expect(find.text('Visits today'), findsNothing);
  });
}
