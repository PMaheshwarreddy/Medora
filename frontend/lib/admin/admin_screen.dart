import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_client.dart';
import '../config/app_config.dart';
import '../kiosk/kiosk_key_store.dart';
import '../state/kiosk_context.dart';
import '../state/service_status.dart';
import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';
import 'admin_widgets.dart';
import 'auth_screen.dart';
import 'clients_tab.dart';
import 'kiosk_tab.dart';
import 'knowledge_tab.dart';
import 'logs_tab.dart';
import 'overview_tab.dart';
import 'sessions_tab.dart';

enum AdminPage {
  dashboard(
    Icons.space_dashboard_outlined,
    'Dashboard',
    'How Medora is doing right now',
  ),
  kiosk(
    Icons.tablet_mac_outlined,
    'Kiosk',
    'Open the patient kiosk as one of your clients',
  ),
  clients(
    Icons.apartment_outlined,
    'Clients & keys',
    'Each hospital, its one key, and what its kiosks offer',
  ),
  sessions(
    Icons.people_alt_outlined,
    'Sessions',
    'Patient intakes across all clients',
  ),
  logs(
    Icons.receipt_long_outlined,
    'Activity logs',
    "What every client's kiosks did, and what went wrong",
  ),
  database(
    Icons.storage_outlined,
    'Database',
    'The medical knowledge and how data gets into it',
  );

  const AdminPage(this.icon, this.label, this.subtitle);

  final IconData icon;
  final String label;
  final String subtitle;
}

/// The company's back office and the app's home: clients, monitoring, the
/// knowledge database, API access and settings, with the patient kiosk
/// opened from its Kiosk section.
class AdminScreen extends ConsumerStatefulWidget {
  const AdminScreen({super.key});

  @override
  ConsumerState<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends ConsumerState<AdminScreen> {
  AdminPage _page = AdminPage.dashboard;
  // True while a remembered sign-in is being checked with the server.
  bool _restoring = false;

  @override
  void initState() {
    super.initState();
    final token = readSessionToken();
    if (token != null && ref.read(adminSessionProvider) == null) {
      _restoring = true;
      _restore(token);
    }
  }

  Future<void> _restore(String token) async {
    final api = ref.read(apiClientProvider);
    try {
      final user = await api.currentUser(token);
      ref
          .read(adminSessionProvider.notifier)
          .unlock(AdminApi(api, token, user));
    } on ApiException catch (e) {
      // Expired or revoked: forget it. A server that cannot be reached is
      // not a reason to sign out.
      if (e.statusCode == 401) saveSessionToken(null);
    }
    if (mounted) setState(() => _restoring = false);
  }

  Future<void> _signOut() async {
    final admin = ref.read(adminSessionProvider);
    saveSessionToken(null);
    ref.read(adminSessionProvider.notifier).lock();
    try {
      await ref.read(apiClientProvider).logout(admin!.token);
    } on ApiException {
      // Signed out here regardless; the session expires on its own.
    }
  }

  /// Opens the patient kiosk as the given client would see it.
  void _openKiosk(Map<String, dynamic> client) {
    final admin = ref.read(adminSessionProvider)!;
    ref
        .read(kioskPreviewProvider.notifier)
        .start(
          KioskPreview(
            clientName: client['name'] as String,
            api: admin.previewing(client['id'] as String),
            config: AppConfig.fromJson(client),
          ),
        );
    context.go('/kiosk');
  }

  @override
  Widget build(BuildContext context) {
    final admin = ref.watch(adminSessionProvider);
    if (admin == null) {
      return _restoring
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : const AuthScreen();
    }

    final wide = MediaQuery.sizeOf(context).width >= 1000;
    return Scaffold(
      backgroundColor: AdminColors.canvas,
      body: SafeArea(
        child: Row(
          children: [
            _Sidebar(
              expanded: wide,
              page: _page,
              user: admin.user,
              onSelect: (page) => setState(() => _page = page),
              onSignOut: _signOut,
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _Header(page: _page),
                  Expanded(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.fromLTRB(28, 4, 28, 28),
                      child: Align(
                        alignment: Alignment.topLeft,
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 1280),
                          // A new key per page so each one loads afresh.
                          child: KeyedSubtree(
                            key: ValueKey(_page),
                            child: switch (_page) {
                              AdminPage.dashboard => OverviewTab(admin: admin),
                              AdminPage.kiosk => KioskTab(
                                admin: admin,
                                onOpen: _openKiosk,
                              ),
                              AdminPage.clients => ClientsTab(
                                admin: admin,
                                onPreviewKiosk: _openKiosk,
                              ),
                              AdminPage.sessions => SessionsTab(admin: admin),
                              AdminPage.logs => LogsTab(admin: admin),
                              AdminPage.database => KnowledgeTab(admin: admin),
                            },
                          ),
                        ),
                      ),
                    ),
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

class _Sidebar extends StatelessWidget {
  const _Sidebar({
    required this.expanded,
    required this.page,
    required this.user,
    required this.onSelect,
    required this.onSignOut,
  });

  /// Labels shown beside the icons; on narrow screens only icons remain.
  final bool expanded;
  final AdminPage page;
  final Map<String, dynamic> user;
  final ValueChanged<AdminPage> onSelect;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: expanded ? 256 : 76,
      decoration: const BoxDecoration(gradient: MedoraTheme.nightGradient),
      padding: EdgeInsets.symmetric(
        horizontal: expanded ? 14 : 10,
        vertical: 18,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: EdgeInsets.only(left: expanded ? 8 : 9, bottom: 26),
            child: Row(
              children: [
                const BrandMark(size: 38),
                if (expanded) ...[
                  const SizedBox(width: 12),
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Medora',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 20,
                          height: 1.1,
                          fontFamily: MedoraFonts.serif,
                          fontWeight: FontWeight.w600,
                          letterSpacing: -0.3,
                        ),
                      ),
                      Text(
                        'Back office',
                        style: TextStyle(
                          color: AdminColors.sidebarText,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          Expanded(
            child: ListView(
              children: [
                for (final p in AdminPage.values)
                  _NavItem(
                    key: ValueKey('nav-${p.name}'),
                    icon: p.icon,
                    label: p.label,
                    expanded: expanded,
                    selected: p == page,
                    onTap: () => onSelect(p),
                  ),
              ],
            ),
          ),
          const Divider(color: Color(0x33FFFFFF), height: 24),
          if (expanded)
            Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0x14FFFFFF),
                borderRadius: BorderRadius.circular(14),
              ),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    alignment: Alignment.center,
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: MedoraTheme.brandGradient,
                    ),
                    child: Text(
                      ((user['name'] as String?) ?? '?').trim().isEmpty
                          ? '?'
                          : (user['name'] as String).trim()[0].toUpperCase(),
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          user['name'] as String? ?? '',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(
                          user['email'] as String? ?? '',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AdminColors.sidebarText,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          _NavItem(
            key: const ValueKey('nav-signout'),
            icon: Icons.logout,
            label: 'Sign out',
            expanded: expanded,
            selected: false,
            onTap: onSignOut,
          ),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    super.key,
    required this.icon,
    required this.label,
    required this.expanded,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool expanded;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = selected ? Colors.white : AdminColors.sidebarText;
    final item = Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Material(
        color: selected ? AdminColors.sidebarActive : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          hoverColor: const Color(0x14FFFFFF),
          onTap: onTap,
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: expanded ? 12 : 0,
              vertical: 12,
            ),
            child: Row(
              mainAxisAlignment: expanded
                  ? MainAxisAlignment.start
                  : MainAxisAlignment.center,
              children: [
                // The current page is marked in terracotta.
                if (expanded)
                  Container(
                    width: 3,
                    height: 20,
                    margin: const EdgeInsets.only(right: 9),
                    decoration: BoxDecoration(
                      color: selected
                          ? MedoraColors.accent
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                Icon(icon, color: color, size: 22),
                if (expanded) ...[
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      label,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: color,
                        fontSize: 15,
                        fontWeight: selected
                            ? FontWeight.w600
                            : FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
    return expanded ? item : Tooltip(message: label, child: item);
  }
}

class _Header extends ConsumerWidget {
  const _Header({required this.page});

  final AdminPage page;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final text = Theme.of(context).textTheme;
    final status = ref.watch(serviceStatusProvider).value;
    final online = status?.online ?? true;
    return Padding(
      padding: const EdgeInsets.fromLTRB(28, 22, 28, 18),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(page.label, style: text.headlineSmall),
                const SizedBox(height: 2),
                Text(
                  page.subtitle,
                  style: text.bodyMedium,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          if (status != null)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: MedoraColors.surface,
                borderRadius: BorderRadius.circular(30),
                boxShadow: MedoraTheme.cardShadow,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 9,
                    height: 9,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: online ? MedoraColors.teal : MedoraColors.warning,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    online ? 'Online' : 'Offline mode',
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                      color: MedoraColors.text,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
