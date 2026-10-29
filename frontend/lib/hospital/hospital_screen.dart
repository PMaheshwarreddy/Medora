import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart' show ApiException;
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart' show BrandMark, MedoraNotice;
import 'hospital_api.dart';
import 'hospital_login.dart';
import 'hospital_session.dart';
import 'pages/activity_page.dart';
import 'pages/dashboard_page.dart';
import 'pages/departments_page.dart';
import 'pages/people_page.dart';
import 'pages/settings_page.dart';
import 'pages/visits_page.dart';

/// The pages of the hospital portal, in sidebar order.
enum HospitalPage {
  dashboard('Dashboard', Icons.space_dashboard_outlined),
  doctors('Doctors', Icons.medical_services_outlined),
  staff('Staff', Icons.badge_outlined),
  departments('Departments', Icons.apartment_outlined),
  visits('Visits and reports', Icons.folder_shared_outlined),
  activity('Audit and activity', Icons.shield_outlined),
  settings('Settings', Icons.tune_rounded);

  const HospitalPage(this.label, this.icon);

  final String label;
  final IconData icon;
}

/// The hospital portal at `/hospital`: a hospital's own back office.
class HospitalScreen extends ConsumerStatefulWidget {
  const HospitalScreen({super.key});

  @override
  ConsumerState<HospitalScreen> createState() => _HospitalScreenState();
}

class _HospitalScreenState extends ConsumerState<HospitalScreen> {
  HospitalPage _page = HospitalPage.dashboard;
  bool _restoring = false;

  @override
  void initState() {
    super.initState();
    // A reload keeps the sign-in.
    final token = ref.read(hospitalSessionProvider.notifier).readToken();
    if (token != null && ref.read(hospitalSessionProvider) == null) {
      _restoring = true;
      _restore(token);
    }
  }

  Future<void> _restore(String token) async {
    final client = ref.read(hospitalClientProvider);
    try {
      final body = await client.me(token);
      ref
          .read(hospitalSessionProvider.notifier)
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
        ref.read(hospitalSessionProvider.notifier).signOut();
      }
    }
    if (mounted) setState(() => _restoring = false);
  }

  Future<void> _signOut() async {
    final api = ref.read(hospitalSessionProvider);
    ref.read(hospitalSessionProvider.notifier).signOut();
    try {
      await api?.send('POST', '/auth/logout');
    } on ApiException {
      // Signed out here regardless; the session expires on its own.
    }
  }

  Widget _content(HospitalApi api) => switch (_page) {
    HospitalPage.dashboard => DashboardPage(
      api: api,
      onOpen: (page) => setState(() => _page = page),
    ),
    HospitalPage.doctors => PeoplePage(
      key: const ValueKey('doctors'),
      api: api,
      role: 'doctor',
    ),
    HospitalPage.staff => PeoplePage(
      key: const ValueKey('staff'),
      api: api,
      role: 'staff',
    ),
    HospitalPage.departments => DepartmentsPage(api: api),
    HospitalPage.visits => VisitsPage(api: api),
    HospitalPage.activity => ActivityPage(api: api),
    HospitalPage.settings => SettingsPage(
      api: api,
      onSaved: (hospital) => ref
          .read(hospitalSessionProvider.notifier)
          .update(api.copyWith(hospital: hospital)),
    ),
  };

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(hospitalSessionProvider);
    if (_restoring) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (api == null) return HospitalLogin(session: hospitalSessionProvider);
    if (api.user['mustChangePassword'] == true) {
      return HospitalPasswordChange(session: hospitalSessionProvider);
    }
    if (!api.isAdmin) return _NotForThisRole(api: api, onSignOut: _signOut);

    final wide = MediaQuery.sizeOf(context).width >= 980;
    final sidebar = _Sidebar(
      api: api,
      current: _page,
      onSelect: (page) {
        setState(() => _page = page);
        if (!wide) Navigator.maybePop(context);
      },
      onSignOut: _signOut,
    );
    return Scaffold(
      backgroundColor: MedoraColors.background,
      drawer: wide ? null : Drawer(child: sidebar),
      appBar: wide
          ? null
          : AppBar(
              title: Text(api.hospital['name'] as String? ?? 'Hospital'),
              backgroundColor: MedoraColors.surface,
            ),
      body: Row(
        children: [
          if (wide) SizedBox(width: 260, child: sidebar),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(28, 28, 28, 40),
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1180),
                  child: _content(api),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({
    required this.api,
    required this.current,
    required this.onSelect,
    required this.onSignOut,
  });

  final HospitalApi api;
  final HospitalPage current;
  final ValueChanged<HospitalPage> onSelect;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final logo = api.hospital['logo'] as String? ?? '';
    final name = api.hospital['name'] as String? ?? 'Hospital';
    return Container(
      color: MedoraColors.primaryDark,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 8),
              child: Row(
                children: [
                  if (logo.startsWith('data:image'))
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.memory(
                        base64Decode(logo.split(',').last),
                        width: 40,
                        height: 40,
                        fit: BoxFit.cover,
                      ),
                    )
                  else
                    const BrandMark(size: 40),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontFamily: MedoraFonts.serif,
                            color: Colors.white,
                            fontSize: 17,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const Text(
                          'Hospital portal',
                          style: TextStyle(
                            color: Color(0xFFB7C6BD),
                            fontSize: 12.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            for (final page in HospitalPage.values)
              _NavItem(
                key: Key('hnav-${page.name}'),
                page: page,
                active: page == current,
                onTap: () => onSelect(page),
              ),
            const Spacer(),
            const Divider(color: Color(0x33FFFFFF), height: 1),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 14, 12, 14),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          api.user['name'] as String? ?? '',
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(
                          api.user['email'] as String? ?? '',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Color(0xFFB7C6BD),
                            fontSize: 12.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    key: const Key('hospital-sign-out'),
                    tooltip: 'Sign out',
                    onPressed: onSignOut,
                    icon: const Icon(Icons.logout_rounded, color: Colors.white),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    super.key,
    required this.page,
    required this.active,
    required this.onTap,
  });

  final HospitalPage page;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      child: Material(
        color: active ? const Color(0x29FFFFFF) : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              border: Border(
                left: BorderSide(
                  color: active ? MedoraColors.accent : Colors.transparent,
                  width: 3,
                ),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  page.icon,
                  size: 20,
                  color: active ? Colors.white : const Color(0xFFB7C6BD),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    page.label,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: active ? Colors.white : const Color(0xFFB7C6BD),
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
}

/// A doctor or staff member who opened the admin portal.
class _NotForThisRole extends StatelessWidget {
  const _NotForThisRole({required this.api, required this.onSignOut});

  final HospitalApi api;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: MedoraColors.background,
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                MedoraNotice(
                  icon: Icons.info_outline,
                  message:
                      'This portal is for the hospital\'s administrators. '
                      '${api.user['name']}, your account is a '
                      '${api.user['role'] == 'doctor' ? 'doctor' : 'staff'} '
                      'account: its own portal is coming next.',
                ),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: onSignOut,
                  child: const Text('Sign out'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
