import 'package:flutter/material.dart';

import '../theme/medora_theme.dart';
import '../widgets/medora_scaffold.dart';
import 'admin_widgets.dart';

/// The way into the patient kiosk: pick a client and use the kiosk exactly
/// as that client's patients would.
class KioskTab extends StatefulWidget {
  const KioskTab({super.key, required this.admin, required this.onOpen});

  final AdminApi admin;
  final ValueChanged<Map<String, dynamic>> onOpen;

  @override
  State<KioskTab> createState() => _KioskTabState();
}

class _KioskTabState extends State<KioskTab> with Loader {
  List<dynamic> _clients = [];

  @override
  Future<void> load() async {
    _clients = await widget.admin.get('/api/admin/tenants') as List;
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...statusWidgets(),
        Text(
          'Patient intakes you complete here are real: they are saved under '
          'the client you chose and appear in Sessions.',
          style: text.bodyMedium,
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 16,
          runSpacing: 16,
          children: [
            for (final c in _clients.cast<Map<String, dynamic>>())
              SizedBox(
                width: 380,
                child: _KioskCard(client: c, onOpen: () => widget.onOpen(c)),
              ),
          ],
        ),
      ],
    );
  }
}

class _KioskCard extends StatelessWidget {
  const _KioskCard({required this.client, required this.onOpen});

  final Map<String, dynamic> client;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final active = client['active'] as bool;
    final offers = [
      if (client['voiceIntake'] == true) 'Voice agent',
      if (client['manualIntake'] == true) 'Manual input',
      if (client['smartBand'] == true) 'Smart band',
    ];
    return MedoraCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              IconBadge(
                Icons.tablet_mac_outlined,
                active ? MedoraColors.teal : MedoraColors.muted,
                size: 52,
                solid: true,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      client['name'] as String,
                      style: text.titleLarge,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (!active)
                const Pill('Switched off', MedoraColors.muted)
              else
                for (final offer in offers) Pill(offer, MedoraColors.primary),
            ],
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: active ? onOpen : null,
            icon: const Icon(Icons.open_in_new),
            label: const Text('Open kiosk'),
          ),
        ],
      ),
    );
  }
}
