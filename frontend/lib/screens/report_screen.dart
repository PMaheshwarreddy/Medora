import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/strings.dart';
import '../state/kiosk_context.dart';
import '../api/api_client.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';
import '../theme/medora_theme.dart';
import '../widgets/panel_orbit.dart';
import '../widgets/patient_report.dart';
import '../widgets/medora_scaffold.dart';

/// Generates and shows the triage report, and sends it to the patient.
class ReportScreen extends ConsumerStatefulWidget {
  const ReportScreen({super.key});

  /// Before the one automatic retry of a failed report.
  static const retryDelay = Duration(seconds: 2);

  @override
  ConsumerState<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends ConsumerState<ReportScreen> {
  TriageReport? _report;
  ServiceStatus _status = const ServiceStatus();
  String? _error;
  bool _loading = false;
  // What the server says it is doing while the report is generated.
  ReportProgress? _progress;
  Timer? _poll;
  // Channels currently sending / already sent.
  final _sending = <String>{};
  final _sent = <String>{};

  ApiClient get _api => ref.read(kioskApiProvider);
  String? get _sessionId => ref.read(intakeProvider).sessionId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  void _follow(String id) {
    _poll?.cancel();
    _progress = null;
    _poll = Timer.periodic(const Duration(milliseconds: 800), (_) async {
      final progress = await _api.reportProgress(id);
      if (mounted && _poll != null && progress != null) {
        setState(() => _progress = progress);
      }
    });
  }

  Future<void> _load() async {
    final id = _sessionId;
    if (id == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    _follow(id);
    try {
      // One quiet retry: a dropped connection or a busy model should not
      // put an error in front of the patient. The server makes a report
      // only once, so asking again is safe.
      TriageReport report;
      try {
        report = await _api.generateReport(id);
      } on ApiException {
        await Future<void>.delayed(ReportScreen.retryDelay);
        report = await _api.generateReport(id);
      }
      // Delivery options are a nicety: without them the report still shows.
      final status = await _api.status().catchError(
        (_) => const ServiceStatus(),
      );
      if (!mounted) return;
      setState(() {
        _report = report;
        _status = status;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      _poll?.cancel();
      _poll = null;
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _send(String channel, String label) async {
    final id = _sessionId;
    if (id == null) return;
    setState(() => _sending.add(channel));
    String message;
    try {
      await _api.sendReport(id, channel);
      _sent.add(channel);
      message = mounted ? S.of(context).sentBy(label) : '';
    } on ApiException catch (e) {
      message = e.message;
    }
    if (!mounted) return;
    setState(() => _sending.remove(channel));
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _download() async {
    final id = _sessionId;
    if (id == null) return;
    final opened = await launchUrl(_api.reportPdfUrl(id));
    if (!opened && mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(S.of(context).couldNotOpen)));
    }
  }

  void _finish() {
    ref.read(intakeProvider.notifier).reset();
    // The next patient starts in the default language.
    ref.read(languageProvider.notifier).reset();
    context.go('/kiosk');
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final s = S.of(context);
    final report = _report;

    final List<Widget> body;
    if (_sessionId == null) {
      body = [
        MedoraNotice(icon: Icons.info_outline, message: s.noIntake),
        const SizedBox(height: 24),
        FilledButton(onPressed: _finish, child: Text(s.startOver)),
      ];
    } else if (_loading) {
      body = [
        const SizedBox(height: 8),
        PanelOrbit(progress: _progress),
        const SizedBox(height: 18),
        Text(
          s.reportTakesMinute,
          style: text.bodyMedium,
          textAlign: TextAlign.center,
        ),
      ];
    } else if (report == null) {
      body = [
        MedoraNotice(
          icon: Icons.error_outline,
          message: _error ?? s.reportFailed,
        ),
        const SizedBox(height: 24),
        FilledButton(onPressed: _load, child: Text(s.tryAgain)),
        const SizedBox(height: 12),
        TextButton(onPressed: _finish, child: Text(s.finish)),
      ];
    } else {
      final patient = ref.watch(intakeProvider.select((s) => s.patient));
      // The patient's report: simple English with Malayalam beneath each
      // part, in the order the manager set (patient, what they told us,
      // vitals, conditions, medicines, precautions).
      final view = report.patientView ?? _legacyView(report, patient);
      // The report is shown in the visit's language only.
      final r = stringsFor(view.language);
      body = [
        // A doctor reviews this hospital's reports: the patient waits to be
        // called, with a code for their final report on their own phone.
        if (report.awaitingDoctor) ...[
          _DoctorNext(sessionId: _sessionId!, api: _api),
          const SizedBox(height: 20),
        ],
        if (view.language != 'en' && !view.bilingual) ...[
          MedoraNotice(
            icon: Icons.translate_rounded,
            message: r.reportInEnglish,
          ),
          const SizedBox(height: 20),
        ],
        _UrgencyBanner(report: report),
        const SizedBox(height: 20),
        PatientCard(view: view),
        if (view.symptoms != null ||
            view.duration != null ||
            view.medicationsTaken != null ||
            view.allergies != null) ...[
          const SizedBox(height: 20),
          ToldUsCard(view: view),
        ],
        if (view.vitals.isNotEmpty) ...[
          const SizedBox(height: 20),
          VitalsCard(view: view),
        ] else if (view.vitalFlags.isNotEmpty) ...[
          const SizedBox(height: 20),
          BiCard(title: r.yourVitals, bullets: view.vitalFlags),
        ],
        if (view.summary != null) ...[
          const SizedBox(height: 20),
          BiCard(title: r.summary, paragraphs: [view.summary!]),
        ],
        if (view.conditions.isNotEmpty) ...[
          const SizedBox(height: 20),
          ConditionsCard(conditions: view.conditions),
        ],
        if (view.medicines.isNotEmpty) ...[
          const SizedBox(height: 20),
          MedicinesCard(medicines: view.medicines),
        ] else if (view.medicinesNote != null) ...[
          const SizedBox(height: 20),
          BiCard(title: r.medicines, paragraphs: [view.medicinesNote!]),
        ],
        if (view.precautions.isNotEmpty) ...[
          const SizedBox(height: 20),
          BiCard(title: r.whileYouWait, bullets: view.precautions),
        ],
        if (view.lifestyle.isNotEmpty) ...[
          const SizedBox(height: 20),
          BiCard(title: r.lifestyleAdvice, bullets: view.lifestyle),
        ],
        const SizedBox(height: 20),
        MedoraCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.getMyReport, style: text.titleLarge),
              const SizedBox(height: 16),
              _DeliveryRow(
                icon: Icons.sms_outlined,
                label: s.textMessage,
                target: patient.phone,
                unavailable: _status.sms ? null : s.smsNotSetUp,
                sending: _sending.contains('sms'),
                sent: _sent.contains('sms'),
                onSend: () => _send('sms', s.textMessage),
              ),
              const Divider(height: 28, color: MedoraColors.border),
              _DeliveryRow(
                icon: Icons.mail_outline,
                label: s.email,
                target: patient.email,
                unavailable: !_status.email
                    ? s.emailNotSetUp
                    : patient.email.isEmpty
                    ? s.noEmail
                    : null,
                sending: _sending.contains('email'),
                sent: _sent.contains('email'),
                onSend: () => _send('email', s.email),
              ),
              const SizedBox(height: 20),
              OutlinedButton.icon(
                onPressed: _download,
                icon: const Icon(Icons.download),
                label: Text(s.downloadPdf),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Text(
          [
            if (view.language == 'en')
              report.disclaimer
            else
              r.reportDisclaimer,
            if (view.note != null)
              view.note!.of(view.language)
            else if (!report.knowledgeUsed)
              s.noKnowledgeBase,
          ].join(' '),
          style: text.bodyMedium?.copyWith(fontSize: 13),
        ),
        const SizedBox(height: 24),
        if (ref.read(intakeProvider).vitals.hasAny) ...[
          Text(r.bandWipe, style: text.bodyMedium?.copyWith(fontSize: 12.5)),
          const SizedBox(height: 12),
        ],
        FilledButton(onPressed: _finish, child: Text(s.finish)),
      ];
    }

    return MedoraScaffold(
      step: FlowStep.report,
      maxWidth: 720,
      child: ReportLanguage(
        code: report?.patientView?.language ?? s.language.code,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(s.yourReport, style: text.headlineSmall),
            const SizedBox(height: 20),
            ...body,
          ],
        ),
      ),
    );
  }
}

/// A report from before the patient view existed, shown the same way
/// (English only).
PatientView _legacyView(TriageReport r, PatientIntake p) =>
    PatientView.fromJson({
      'patient': {
        'name': p.name,
        'age': p.age,
        'gender': p.gender?.name,
        'phone': p.phone,
      },
      'summary': {
        'en': r.clinicalSummary.isNotEmpty ? r.clinicalSummary : r.summary,
      },
      'symptoms': {'en': p.symptoms},
      'duration': {'en': p.duration},
      'medicationsTaken': {'en': p.medications},
      'allergies': {'en': p.allergies},
      'conditions': [
        for (final c in r.possibleConditions)
          {
            'name': {'en': c.name},
            'likelihood': c.likelihood,
          },
      ],
      'medicines': [
        for (final m in r.medicines)
          {
            'name': m.name,
            'prescription': m.prescription,
            'howToTake': {
              'en': [
                m.dose,
                m.frequency,
                m.duration,
              ].where((x) => x.isNotEmpty).join(', '),
            },
            'purpose': {'en': m.purpose},
            'caution': {'en': m.caution},
          },
      ],
      'vitals': [
        for (final v in r.vitals)
          {
            'name': v.name,
            'value': v.value,
            'normal': v.normal,
            'status': v.status,
            'note': {'en': v.note},
          },
      ],
      'vitalFlags': [
        for (final f in r.vitalFlags) {'en': f},
      ],
      'precautions': [
        for (final x in r.precautions) {'en': x},
      ],
      'lifestyle': [
        for (final x in r.lifestyleAdvice) {'en': x},
      ],
      'medicinesNote': {'en': r.medicinesNote},
      'bilingual': false,
    });

class _UrgencyBanner extends StatelessWidget {
  const _UrgencyBanner({required this.report});

  final TriageReport report;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    final (color, icon) = switch (report.urgency) {
      Urgency.routine => (MedoraColors.teal, Icons.check_circle),
      Urgency.soon => (MedoraColors.primary, Icons.schedule),
      Urgency.urgent => (MedoraColors.warning, Icons.priority_high),
      Urgency.emergency => (MedoraColors.danger, Icons.warning_amber),
    };
    final body = Theme.of(context).textTheme.bodyLarge;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 36),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  r.urgency(report.urgency.name),
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                ),
                const SizedBox(height: 6),
                Text(r.department(report.department), style: body),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DeliveryRow extends StatelessWidget {
  const _DeliveryRow({
    required this.icon,
    required this.label,
    required this.target,
    required this.unavailable,
    required this.sending,
    required this.sent,
    required this.onSend,
  });

  final IconData icon;
  final String label;
  final String target;

  /// Why this channel cannot be used, or null when it can.
  final String? unavailable;
  final bool sending;
  final bool sent;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Row(
      children: [
        Icon(icon, color: MedoraColors.muted),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: text.titleMedium),
              Text(
                unavailable ?? target,
                style: text.bodyMedium,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        OutlinedButton(
          onPressed: unavailable != null || sending ? null : onSend,
          child: Text(
            sending
                ? S.of(context).sending
                : sent
                ? S.of(context).sendAgain
                : S.of(context).send,
          ),
        ),
      ],
    );
  }
}

/// What happens next when a doctor reviews the report: wait to be called,
/// the visit number the doctor calls out, and a QR code for the patient's
/// own page, where the doctor's signed report appears.
class _DoctorNext extends StatelessWidget {
  const _DoctorNext({required this.sessionId, required this.api});

  final String sessionId;
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    final r = ReportLanguage.stringsOf(context);
    final text = Theme.of(context).textTheme;
    final number = sessionId.substring(0, 6).toUpperCase();
    return MedoraCard(
      child: Wrap(
        spacing: 24,
        runSpacing: 16,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(r.visitNumber(number), style: text.titleLarge),
                const SizedBox(height: 10),
                Text(r.doctorWillSee, style: text.bodyLarge),
                const SizedBox(height: 10),
                Text(r.scanForFinal, style: text.bodyMedium),
              ],
            ),
          ),
          Container(
            key: const Key('final-report-qr'),
            padding: const EdgeInsets.all(10),
            color: Colors.white,
            child: QrImageView(
              data: api.patientPage(sessionId).toString(),
              size: 170,
              backgroundColor: Colors.white,
            ),
          ),
        ],
      ),
    );
  }
}
