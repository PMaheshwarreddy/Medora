import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart' show ApiException;
import '../hospital/hospital_api.dart';
import '../hospital/hospital_login.dart';
import '../hospital/hospital_session.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart' show BrandMark, MedoraNotice;
import 'doctor_widgets.dart';
import 'pages/consult_page.dart';
import 'pages/consultations_page.dart';
import 'pages/queue_page.dart';

/// The doctor portal at `/doctor`: the patient queue, the consultation
/// (Medora's doctor report, history, and the doctor's own decisions), and
/// the doctor's signed consultations. Doctors sign in with the hospital
/// account their hospital's admin made.
class DoctorScreen extends ConsumerStatefulWidget {
  const DoctorScreen({super.key});

  @override
  ConsumerState<DoctorScreen> createState() => _DoctorScreenState();
}

class _DoctorScreenState extends ConsumerState<DoctorScreen> {
  bool _restoring = false;
  int _tab = 0;

  /// The visit being consulted, or null for the lists.
  String? _visit;

  @override
  void initState() {
    super.initState();
    final token = ref.read(doctorSessionProvider.notifier).readToken();
    if (token != null && ref.read(doctorSessionProvider) == null) {
      _restoring = true;
      _restore(token);
    }
  }

  Future<void> _restore(String token) async {
    final client = ref.read(hospitalClientProvider);
    try {
      final body = await client.me(token);
      ref
          .read(doctorSessionProvider.notifier)
          .signIn(
            HospitalApi(
              client,
              token,
              (body['user'] as Map).cast<String, dynamic>(),
              (body['hospital'] as Map).cast<String, dynamic>(),
            ),
          );
    } on ApiException catch (e) {
      if (e.statusCode == 401) {
        ref.read(doctorSessionProvider.notifier).signOut();
      }
    }
    if (mounted) setState(() => _restoring = false);
  }

  Future<void> _signOut() async {
    final api = ref.read(doctorSessionProvider);
    ref.read(doctorSessionProvider.notifier).signOut();
    setState(() => _visit = null);
    try {
      await api?.send('POST', '/auth/logout');
    } on ApiException {
      // Signed out here regardless.
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(doctorSessionProvider);
    if (_restoring) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (api == null) {
      return HospitalLogin(
        session: doctorSessionProvider,
        title: 'Doctor portal',
      );
    }
    if (api.user['mustChangePassword'] == true) {
      return HospitalPasswordChange(session: doctorSessionProvider);
    }
    if (api.user['role'] != 'doctor') {
      return Scaffold(
        backgroundColor: MedoraColors.background,
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const MedoraNotice(
                    icon: Icons.info_outline,
                    message:
                        'The doctor portal is for doctors. Hospital '
                        'administrators use the hospital portal.',
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _signOut,
                    child: const Text('Sign out'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }
    final doctorApi = DoctorApi(api);
    final Widget content = _visit != null
        ? ConsultPage(
            key: ValueKey(_visit),
            api: doctorApi,
            visitId: _visit!,
            onClose: () => setState(() => _visit = null),
          )
        : _tab == 0
        ? QueuePage(api: doctorApi, onOpen: (id) => setState(() => _visit = id))
        : ConsultationsPage(api: doctorApi);
    final body = SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(28, 26, 28, 48),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1320),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_visit == null) ...[
                _Greeting(name: api.user['name'] as String? ?? ''),
                const SizedBox(height: 22),
              ],
              content,
            ],
          ),
        ),
      ),
    );
    final hospitalName = api.hospital['name'] as String? ?? '';
    void go(int tab) => setState(() {
      _tab = tab;
      _visit = null;
    });
    final wide = MediaQuery.sizeOf(context).width >= 980;
    if (wide) {
      return Scaffold(
        backgroundColor: MedoraColors.background,
        body: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Sidebar(
              hospital: hospitalName,
              user: api.user,
              tab: _visit == null ? _tab : -1,
              onTab: go,
              onSignOut: _signOut,
            ),
            Expanded(child: body),
          ],
        ),
      );
    }
    return Scaffold(
      backgroundColor: MedoraColors.background,
      appBar: AppBar(
        backgroundColor: MedoraColors.primaryDark,
        foregroundColor: Colors.white,
        titleSpacing: 16,
        title: Row(
          children: [
            const BrandMark(size: 32),
            const SizedBox(width: 10),
            Flexible(
              child: Text(
                hospitalName,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontFamily: MedoraFonts.serif,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        actions: [
          _TabButton(
            key: const Key('dtab-queue'),
            label: 'Queue',
            active: _visit == null && _tab == 0,
            onTap: () => go(0),
          ),
          _TabButton(
            key: const Key('dtab-done'),
            label: 'Signed',
            active: _visit == null && _tab == 1,
            onTap: () => go(1),
          ),
          IconButton(
            key: const Key('doctor-sign-out'),
            tooltip: 'Sign out',
            onPressed: _signOut,
            icon: const Icon(Icons.logout_rounded),
          ),
          const SizedBox(width: 6),
        ],
      ),
      body: body,
    );
  }
}

/// "Good morning, Dr. Anita Nair" and today's date.
class _Greeting extends StatelessWidget {
  const _Greeting({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final part = now.hour < 12
        ? 'Good morning'
        : now.hour < 17
        ? 'Good afternoon'
        : 'Good evening';
    const days = [
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ]; // fmt: skip
    const months = [
      'January',
      'February',
      'March',
      'April',
      'May',
      'June',
      'July',
      'August',
      'September',
      'October',
      'November',
      'December',
    ]; // fmt: skip
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${days[now.weekday - 1]}, ${now.day} ${months[now.month - 1]}'
              .toUpperCase(),
          style: text.bodySmall?.copyWith(
            letterSpacing: 1.4,
            fontWeight: FontWeight.w700,
            color: MedoraColors.accent,
          ),
        ),
        const SizedBox(height: 6),
        Text.rich(
          TextSpan(
            children: [
              TextSpan(text: '$part, '),
              TextSpan(
                text: name,
                style: const TextStyle(fontStyle: FontStyle.italic),
              ),
            ],
          ),
          style: const TextStyle(
            fontFamily: MedoraFonts.serif,
            fontSize: 34,
            height: 1.15,
            fontWeight: FontWeight.w500,
            color: MedoraColors.navy,
          ),
        ),
      ],
    );
  }
}

/// The dark pine column on the left: brand, hospital, the two pages, and
/// the signed-in doctor.
class _Sidebar extends StatelessWidget {
  const _Sidebar({
    required this.hospital,
    required this.user,
    required this.tab,
    required this.onTab,
    required this.onSignOut,
  });

  final String hospital;
  final Map<String, dynamic> user;

  /// The open page, or -1 during a consultation.
  final int tab;
  final ValueChanged<int> onTab;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final qualification = '${user['qualification'] ?? ''}'.trim();
    final registration = '${user['registrationNumber'] ?? ''}'.trim();
    return Container(
      width: 264,
      decoration: const BoxDecoration(
        color: MedoraColors.primaryDark,
        border: Border(right: BorderSide(color: Color(0x14000000))),
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 24, 18, 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const BrandMark(size: 38),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Medora',
                          style: TextStyle(
                            fontFamily: MedoraFonts.serif,
                            fontSize: 21,
                            fontWeight: FontWeight.w600,
                            color: Colors.white,
                          ),
                        ),
                        Text(
                          'CLINICIAN',
                          style: TextStyle(
                            fontSize: 10.5,
                            letterSpacing: 2,
                            fontWeight: FontWeight.w700,
                            color: Colors.white.withValues(alpha: 0.55),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 26),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: Colors.white.withValues(alpha: 0.08),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.local_hospital_outlined,
                      size: 18,
                      color: Colors.white.withValues(alpha: 0.7),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        hospital,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              _NavItem(
                key: const Key('dtab-queue'),
                icon: Icons.people_alt_outlined,
                label: 'Patient queue',
                active: tab == 0,
                onTap: () => onTab(0),
              ),
              _NavItem(
                key: const Key('dtab-done'),
                icon: Icons.task_alt_rounded,
                label: 'My consultations',
                active: tab == 1,
                onTap: () => onTab(1),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.fromLTRB(12, 12, 4, 12),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Row(
                  children: [
                    Initials(
                      user['name'],
                      size: 40,
                      color: MedoraColors.accent,
                      filled: true,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${user['name'] ?? ''}',
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          if (qualification.isNotEmpty ||
                              registration.isNotEmpty)
                            Text(
                              [
                                if (qualification.isNotEmpty) qualification,
                                if (registration.isNotEmpty) registration,
                              ].join(' · '),
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 12,
                                color: Colors.white.withValues(alpha: 0.6),
                              ),
                            ),
                        ],
                      ),
                    ),
                    IconButton(
                      key: const Key('doctor-sign-out'),
                      tooltip: 'Sign out',
                      onPressed: onSignOut,
                      color: Colors.white70,
                      icon: const Icon(Icons.logout_rounded, size: 20),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    super.key,
    required this.icon,
    required this.label,
    required this.active,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 4),
    child: Material(
      color: active ? Colors.white.withValues(alpha: 0.1) : Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          child: Row(
            children: [
              Container(
                width: 3,
                height: 18,
                decoration: BoxDecoration(
                  color: active ? MedoraColors.accent : Colors.transparent,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(width: 10),
              Icon(
                icon,
                size: 20,
                color: active ? Colors.white : Colors.white60,
              ),
              const SizedBox(width: 12),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: active ? Colors.white : Colors.white70,
                    fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _TabButton extends StatelessWidget {
  const _TabButton({
    super.key,
    required this.label,
    required this.active,
    required this.onTap,
  });

  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 3),
    child: TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
        foregroundColor: Colors.white,
        backgroundColor: active ? const Color(0x29FFFFFF) : Colors.transparent,
      ),
      child: Text(label),
    ),
  );
}

/// The doctor API (`/api/doctor/...`) with the doctor's hospital sign-in.
class DoctorApi {
  DoctorApi(this.hospital);

  final HospitalApi hospital;

  Map<String, dynamic> get user => hospital.user;

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      hospital.raw('GET', '/api/doctor$path', query: query);

  Future<dynamic> send(String method, String path, {Object? body}) =>
      hospital.raw(method, '/api/doctor$path', body: body);

  /// The patient's page and the signed PDF, for after finalising.
  Uri patientPdf(String visitId) =>
      hospital.uri('/api/sessions/$visitId/final.pdf');
}
