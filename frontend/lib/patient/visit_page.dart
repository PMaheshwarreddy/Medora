import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../l10n/strings.dart';
import '../models/intake.dart';
import '../widgets/medora_scaffold.dart';
import '../widgets/patient_report.dart';

/// `/r/<visit>`: the patient's own page, from the QR on the kiosk's report
/// screen or the phone after sending the details. It says where the visit
/// is, and shows the doctor's signed report, in simple English with
/// Malayalam beneath, once the doctor has finalised it.
class VisitPage extends ConsumerStatefulWidget {
  const VisitPage({super.key, required this.sessionId});

  final String sessionId;

  /// How often the page checks for the doctor's report.
  static const poll = Duration(seconds: 10);

  @override
  ConsumerState<VisitPage> createState() => _VisitPageState();
}

class _VisitPageState extends ConsumerState<VisitPage> {
  VisitStatus? _status;
  String? _error;
  Timer? _timer;

  ApiClient get _api => ref.read(apiClientProvider);

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
    _timer = Timer.periodic(VisitPage.poll, (_) {
      if (_status?.status != 'final') _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final status = await _api.visitStatus(widget.sessionId);
      if (mounted) {
        setState(() {
          _status = status;
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final text = Theme.of(context).textTheme;
    final status = _status;
    final List<Widget> body;
    if (status == null) {
      body = [
        if (_error != null)
          MedoraNotice(icon: Icons.error_outline, message: _error!)
        else
          const Center(child: CircularProgressIndicator()),
      ];
    } else if (status.report case final report?) {
      body = [
        ReportLanguage(
          code: report.view.language,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: _finalReport(context, s, report),
          ),
        ),
      ];
    } else {
      final message = switch (status.status) {
        'in_consultation' => s.resultWithDoctor(status.doctor),
        'no_review' => s.resultNoReview,
        'preparing' => s.resultPreparing,
        _ => s.resultWaiting,
      };
      body = [
        MedoraCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(s.visitNumber(status.visitNumber), style: text.titleLarge),
              const SizedBox(height: 14),
              Row(
                children: [
                  if (status.status != 'no_review') ...[
                    const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 12),
                  ],
                  Expanded(child: Text(message, style: text.bodyLarge)),
                ],
              ),
            ],
          ),
        ),
      ];
    }
    return MedoraScaffold(
      maxWidth: 720,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            status != null && status.firstName.isNotEmpty
                ? '${s.resultTitle}, ${status.firstName}'
                : s.resultTitle,
            style: text.headlineSmall,
          ),
          const SizedBox(height: 20),
          ...body,
        ],
      ),
    );
  }

  List<Widget> _finalReport(BuildContext context, S s, FinalReport report) {
    final text = Theme.of(context).textTheme;
    final view = report.view;
    // The report is in the visit's language only.
    final r = stringsFor(view.language);
    return [
      MedoraCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(report.hospitalName, style: text.titleLarge),
            if (report.hospitalAddress.isNotEmpty)
              Text(report.hospitalAddress, style: text.bodyMedium),
            const SizedBox(height: 8),
            Text(s.visitNumber(report.visitNumber), style: text.bodyMedium),
          ],
        ),
      ),
      if (view.language != 'en' && !view.bilingual) ...[
        const SizedBox(height: 16),
        MedoraNotice(icon: Icons.translate_rounded, message: r.reportInEnglish),
      ],
      const SizedBox(height: 20),
      PatientCard(view: view),
      if (view.conditions.isNotEmpty) ...[
        const SizedBox(height: 20),
        BiCard(
          title: r.diagnosisLabel,
          paragraphs: [
            for (final c in view.conditions) ...[c.name, ?c.about],
          ],
        ),
      ],
      const SizedBox(height: 20),
      if (view.medicines.isNotEmpty)
        MedicinesCard(medicines: view.medicines, prescribed: true)
      else
        BiCard(
          title: r.prescribedLabel,
          paragraphs: [Bi(r.noMedicinePrescribed)],
        ),
      if (view.tests.isNotEmpty) ...[
        const SizedBox(height: 20),
        BiCard(title: r.testsLabel, bullets: view.tests),
      ],
      if (view.precautions.isNotEmpty) ...[
        const SizedBox(height: 20),
        BiCard(title: r.lifestyleAdvice, bullets: view.precautions),
      ],
      if (view.followUp case final followUp?) ...[
        const SizedBox(height: 20),
        BiCard(title: r.followUpLabel, paragraphs: [followUp]),
      ],
      const SizedBox(height: 20),
      MedoraCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(r.signedBy, style: text.bodyMedium?.copyWith(fontSize: 13)),
            Text(report.doctorName, style: text.titleLarge),
            Text(
              [
                report.doctorQualification,
                report.department,
              ].where((x) => x.isNotEmpty).join(', '),
            ),
            Text('${r.registrationLabel}: ${report.registrationNumber}'),
          ],
        ),
      ),
      const SizedBox(height: 20),
      FilledButton.icon(
        key: const Key('download-prescription'),
        onPressed: () => launchUrl(_api.finalPdfUrl(widget.sessionId)),
        icon: const Icon(Icons.download_rounded),
        label: Text(s.downloadPrescription),
      ),
    ];
  }
}
