import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'admin/admin_screen.dart';
import 'api/api_client.dart';
import 'config/app_config.dart';
import 'doctor/doctor_screen.dart';
import 'hospital/hospital_screen.dart';
import 'kiosk/kiosk_key_store.dart';
import 'patient/phone_intake_page.dart';
import 'patient/visit_page.dart';
import 'l10n/strings.dart';
import 'screens/manual_intake_screen.dart';
import 'screens/phone_handoff_screen.dart';
import 'screens/report_screen.dart';
import 'screens/review_screen.dart';
import 'screens/vitals_screen.dart';
import 'screens/voice_intake_screen.dart';
import 'screens/welcome_screen.dart';
import 'state/kiosk_context.dart';
import 'theme/medora_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final file = await AppConfig.loadLocalFile();
  // A kiosk is tied to its client by opening its link once
  // (`/#/kiosk?key=mk_...`); after that the browser remembers the key.
  final fromLink = Uri.tryParse(Uri.base.fragment)?.queryParameters['key'];
  if (fromLink != null && fromLink.isNotEmpty) saveKioskKey(fromLink);
  final kioskKey =
      fromLink ?? readKioskKey() ?? file['kioskKey'] as String? ?? '';
  final api = ApiClient(kioskKey: kioskKey);
  final config = await AppConfig.load(api, file);
  runApp(
    ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(api),
        appConfigProvider.overrideWithValue(config),
      ],
      child: const MedoraApp(),
    ),
  );
}

/// The back office is the app's home; the kiosk lives under `/kiosk`.
/// [config] is read on every navigation because a back-office preview
/// switches the kiosk to another client's settings.
GoRouter buildRouter(AppConfig Function() config) => GoRouter(
  // Keeps switched-off features unreachable even by URL.
  redirect: (_, state) => switch (state.matchedLocation) {
    '/admin' => '/',
    '/kiosk/voice' when !config().voiceIntake => '/kiosk',
    '/kiosk/manual' when !config().manualIntake => '/kiosk',
    '/kiosk/phone' when !config().manualIntake => '/kiosk',
    '/kiosk/vitals' when !config().smartBand => '/kiosk/review',
    _ => null,
  },
  routes: [
    GoRoute(path: '/', builder: (_, _) => const AdminScreen()),
    GoRoute(path: '/admin', builder: (_, _) => const AdminScreen()),
    // A hospital's own portal (lib/hospital/), apart from the company back office.
    GoRoute(path: '/hospital', builder: (_, _) => const HospitalScreen()),
    // The doctor portal (lib/doctor/): queue, consultation, signing.
    GoRoute(path: '/doctor', builder: (_, _) => const DoctorScreen()),
    // On the patient's own phone: the intake from the kiosk's QR code, and
    // the visit's page with the doctor's signed report (lib/patient/).
    GoRoute(
      path: '/phone/:code',
      builder: (_, state) =>
          PhoneIntakePage(code: state.pathParameters['code']!),
    ),
    GoRoute(
      path: '/r/:id',
      builder: (_, state) => VisitPage(sessionId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/kiosk',
      builder: (_, _) => const WelcomeScreen(),
      routes: [
        GoRoute(path: 'voice', builder: (_, _) => const VoiceIntakeScreen()),
        GoRoute(path: 'manual', builder: (_, _) => const ManualIntakeScreen()),
        GoRoute(path: 'phone', builder: (_, _) => const PhoneHandoffScreen()),
        GoRoute(path: 'vitals', builder: (_, _) => const VitalsScreen()),
        GoRoute(path: 'review', builder: (_, _) => const ReviewScreen()),
        GoRoute(path: 'report', builder: (_, _) => const ReportScreen()),
      ],
    ),
  ],
);

class MedoraApp extends ConsumerStatefulWidget {
  const MedoraApp({super.key, this.initialLocation});

  /// Where to start; tests use it to open the kiosk directly.
  final String? initialLocation;

  @override
  ConsumerState<MedoraApp> createState() => _MedoraAppState();
}

class _MedoraAppState extends ConsumerState<MedoraApp> {
  late final GoRouter _router = _build();

  GoRouter _build() {
    final router = buildRouter(() => ref.read(kioskConfigProvider));
    if (widget.initialLocation != null) router.go(widget.initialLocation!);
    return router;
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'Medora',
      debugShowCheckedModeBanner: false,
      theme: MedoraTheme.light(),
      routerConfig: _router,
      // The kiosk's language, for every screen below (l10n/strings.dart).
      builder: (context, child) => StringsScope(
        strings: ref.watch(stringsProvider),
        child: child ?? const SizedBox.shrink(),
      ),
    );
  }
}
