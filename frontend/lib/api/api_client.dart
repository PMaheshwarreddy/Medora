import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/intake.dart';

/// Set at build time: `--dart-define=MEDORA_API=https://api.example.com`.
const _apiDefine = String.fromEnvironment('MEDORA_API');

/// The API's address. Without MEDORA_API: port 8100 on the machine this page
/// came from, so a phone that opened the app at http://192.168.x.x:8080
/// calls http://192.168.x.x:8100 (for it, "localhost" is the phone itself).
final String medoraApiBase = _apiDefine.isNotEmpty ? _apiDefine : _sameHost();

String _sameHost() {
  final host = Uri.base.host;
  if (!Uri.base.scheme.startsWith('http') || host.isEmpty) {
    return 'http://localhost:8100';
  }
  return 'http://$host:8100';
}

/// Where patients' phones reach this app, for the QR codes the kiosk shows
/// (`--dart-define=MEDORA_PUBLIC_URL=https://medora.example.com`). Empty =
/// the address the kiosk itself was opened at (see [publicBase]).
const medoraPublicUrl = String.fromEnvironment('MEDORA_PUBLIC_URL');

/// This server's address on the local network, as `/api/status` last
/// reported it (fresh every few seconds, so a changed Wi-Fi address is
/// followed). Empty until known.
String serverLanAddress = '';

/// A page of this app (e.g. `/r/<visit>`) as a link a phone can open.
Uri publicLink(String route) => publicBase(
  Uri.base,
  medoraPublicUrl,
  serverLanAddress,
).replace(fragment: route);

/// The address phones should use, from where the kiosk was [opened], the
/// build's [define] (MEDORA_PUBLIC_URL) and the server's [lan] address:
/// - a real domain in [define] (https://medora.example.com) always wins;
/// - a kiosk opened as localhost uses the server's current network address
///   with the port the app is served on (a phone cannot reach "localhost",
///   and an address baked in at start goes stale when the Wi-Fi changes);
/// - else [define], else the kiosk's own address.
Uri publicBase(Uri opened, String define, String lan) {
  final defined = define.isEmpty ? null : Uri.tryParse(define);
  bool isIp(String host) =>
      RegExp(r'^\d{1,3}(\.\d{1,3}){3}$').hasMatch(host) || host.contains(':');
  if (defined != null &&
      defined.host.isNotEmpty &&
      defined.host != 'localhost' &&
      !isIp(defined.host)) {
    return defined;
  }
  final local = {'localhost', '127.0.0.1', '::1', ''}.contains(opened.host);
  if (local && lan.isNotEmpty) {
    final port = opened.hasPort
        ? opened.port
        : (defined != null && defined.hasPort ? defined.port : null);
    return Uri(
      scheme: 'http',
      host: lan,
      port: port,
      path: opened.path.isEmpty ? '/' : opened.path,
    );
  }
  if (defined != null) return defined;
  return Uri(
    scheme: opened.scheme,
    host: opened.host,
    port: opened.hasPort ? opened.port : null,
    path: opened.path,
  );
}

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  /// Null when the server could not be reached at all.
  final int? statusCode;
  final String message;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({
    http.Client? client,
    String? base,
    this.kioskKey = '',
    this.previewAdminKey,
    this.previewTenantId,
  }) : _http = client ?? http.Client(),
       base = base ?? medoraApiBase;

  final http.Client _http;
  final String base;

  /// Identifies this kiosk's client (hospital). Empty = the default client.
  final String kioskKey;

  /// Set together when the back office previews a client's kiosk: requests
  /// then act as that client, authorised by the admin key.
  final String? previewAdminKey;
  final String? previewTenantId;

  /// The same connection, acting as [tenantId] for a back-office preview.
  ApiClient previewing(String adminKey, String tenantId) => ApiClient(
    client: _http,
    base: base,
    previewAdminKey: adminKey,
    previewTenantId: tenantId,
  );

  Uri _uri(String path, [Map<String, String>? query]) => Uri.parse(
    '$base$path',
  ).replace(queryParameters: (query == null || query.isEmpty) ? null : query);

  Map<String, String> _headers({String? adminKey, bool json = false}) => {
    'X-Admin-Key': ?adminKey,
    if (adminKey == null && previewTenantId != null) ...{
      'X-Admin-Key': previewAdminKey!,
      'X-Tenant-Id': previewTenantId!,
    } else if (adminKey == null && kioskKey.isNotEmpty)
      'X-Kiosk-Key': kioskKey,
    if (json) 'Content-Type': 'application/json',
  };

  Future<dynamic> _send(
    Future<http.Response> Function() request, {
    Duration timeout = const Duration(seconds: 20),
  }) async {
    final http.Response response;
    try {
      response = await request().timeout(timeout);
    } catch (_) {
      throw ApiException(null, 'Cannot reach the Medora server at $base');
    }
    return _decode(response);
  }

  dynamic _decode(http.Response response) {
    final body = response.body.isEmpty
        ? null
        : jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode >= 400) {
      final detail = body is Map ? body['detail'] : null;
      throw ApiException(
        response.statusCode,
        detail is String ? detail : 'Request failed (${response.statusCode})',
      );
    }
    return body;
  }

  // --- Kiosk -------------------------------------------------------------

  Future<AppConfig> fetchConfig() async {
    final body = await _send(
      () => _http.get(_uri('/api/config'), headers: _headers()),
    );
    return AppConfig.fromJson(body as Map<String, dynamic>);
  }

  /// Stores the confirmed intake and returns its session id.
  Future<String> createSession(
    IntakeSession session, [
    String language = 'en',
  ]) async {
    final p = session.patient;
    final v = session.vitals;
    final body = await _send(
      () => _http.post(
        _uri('/api/sessions'),
        headers: _headers(json: true),
        body: jsonEncode({
          'mode': (session.mode ?? IntakeMode.manual).name,
          'name': p.name,
          'age': p.age,
          'gender': p.gender?.name,
          'phone': p.phone,
          'email': p.email,
          'symptoms': p.symptoms,
          'duration': p.duration,
          'medications': p.medications,
          'allergies': p.allergies,
          'pregnancy': p.pregnancy,
          'chronicConditions': p.conditions,
          'regularMedicines': p.regularMedicines,
          'pastSurgeries': p.surgeries,
          'habits': p.habits,
          'weightKg': ?p.weightKg,
          'patientId': ?p.patientId,
          'language': language,
          'vitals': v.hasAny
              ? {
                  'heartRate': v.heartRate,
                  'spo2': v.spo2,
                  'temperatureC': v.temperatureC,
                  'systolic': v.systolic,
                  'diastolic': v.diastolic,
                }
              : null,
        }),
      ),
    );
    return (body as Map)['id'] as String;
  }

  Future<ServiceStatus> status() async {
    final body = await _send(() => _http.get(_uri('/api/status')));
    final status = ServiceStatus.fromJson(body as Map<String, dynamic>);
    if (status.lanAddress.isNotEmpty) serverLanAddress = status.lanAddress;
    return status;
  }

  /// The person an earlier [visit] number belongs to (full name and age),
  /// for "Have you visited before?". Empty when offline or on any failure.
  Future<List<({String id, String label, int? age})>> findPatients(
    String visit,
  ) async {
    try {
      final body = await _send(
        () => _http.post(
          _uri('/api/intake/patients'),
          headers: _headers(json: true),
          body: jsonEncode({'visit': visit}),
        ),
        timeout: const Duration(seconds: 10),
      );
      return [
        for (final p in body as List)
          (
            id: (p as Map)['id'] as String,
            label: p['label'] as String,
            age: p['age'] as int?,
          ),
      ];
    } on ApiException {
      return const [];
    }
  }

  /// A code to show as a QR, for filling the intake on a phone.
  Future<String> openHandoff(String language) async {
    final body = await _send(
      () => _http.post(
        _uri('/api/handoffs'),
        headers: _headers(json: true),
        body: jsonEncode({'language': language}),
      ),
    );
    return (body as Map)['code'] as String;
  }

  /// `(status, intake)`: intake once the phone has sent it.
  Future<({String status, Map<String, dynamic>? intake})> handoffStatus(
    String code,
  ) async {
    final body =
        await _send(
              () => _http.get(_uri('/api/handoffs/$code'), headers: _headers()),
              timeout: const Duration(seconds: 10),
            )
            as Map<String, dynamic>;
    return (
      status: body['status'] as String,
      intake: (body['intake'] as Map?)?.cast<String, dynamic>(),
    );
  }

  /// Tells the phone which visit its details became.
  Future<void> handoffDone(String code, String sessionId) => _send(
    () => _http.post(
      _uri('/api/handoffs/$code/done'),
      headers: _headers(json: true),
      body: jsonEncode({'sessionId': sessionId}),
    ),
  );

  // --- The patient's phone (no kiosk key: the code is the access) -------

  Future<({String status, String language, String hospital, String? sessionId})>
  phoneHandoff(String code) async {
    final body =
        await _send(() => _http.get(_uri('/api/handoffs/$code/phone')))
            as Map<String, dynamic>;
    return (
      status: body['status'] as String,
      language: body['language'] as String? ?? 'en',
      hospital: body['hospital'] as String? ?? '',
      sessionId: body['sessionId'] as String?,
    );
  }

  Future<void> phoneSubmit(
    String code,
    PatientIntake patient,
    String language,
  ) => _send(
    () => _http.post(
      _uri('/api/handoffs/$code/phone'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(
        {...patient.toJson(), 'language': language}
          ..removeWhere((k, v) => v == null),
      ),
    ),
  );

  Future<List<({String id, String label, int? age})>> phoneFindPatients(
    String code,
    String visit,
  ) async {
    try {
      final body = await _send(
        () => _http.post(
          _uri('/api/handoffs/$code/phone/patients'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'visit': visit}),
        ),
      );
      return [
        for (final p in body as List)
          (
            id: (p as Map)['id'] as String,
            label: p['label'] as String,
            age: p['age'] as int?,
          ),
      ];
    } on ApiException {
      return const [];
    }
  }

  /// Where a visit is, and the doctor's signed report once there is one.
  Future<VisitStatus> visitStatus(String sessionId) async =>
      VisitStatus.fromJson(
        await _send(() => _http.get(_uri('/api/sessions/$sessionId/final')))
            as Map<String, dynamic>,
      );

  Uri finalPdfUrl(String sessionId) =>
      _uri('/api/sessions/$sessionId/final.pdf');

  /// The patient's own page for this visit (the QR on the report screen).
  Uri patientPage(String sessionId) => publicLink('/r/$sessionId');

  /// Runs the analysis. Offline the whole report runs on the local medical
  /// model, which on a laptop without a GPU took about 20 minutes
  /// (2026-10-29, i7-1355U), so the kiosk waits up to 30. A repeated request
  /// joins the report being written.
  Future<TriageReport> generateReport(String sessionId) async {
    final body = await _send(
      () => _http.post(_uri('/api/sessions/$sessionId/report')),
      timeout: const Duration(minutes: 30),
    );
    return TriageReport.fromJson(body as Map<String, dynamic>);
  }

  /// Whether this complaint calls for vitals, and why not when it does not.
  /// Any failure means yes: a measurement is never skipped by accident.
  Future<({bool needed, String reason})> vitalsCheck(
    PatientIntake p, [
    String language = 'en',
  ]) async {
    try {
      final body = await _send(
        () => _http.post(
          _uri('/api/intake/vitals-check'),
          headers: _headers(json: true),
          body: jsonEncode({
            'symptoms': p.symptoms,
            'age': ?p.age,
            'duration': p.duration,
            'language': language,
          }),
        ),
        timeout: const Duration(seconds: 15),
      );
      final map = body as Map<String, dynamic>;
      return (
        needed: map['needed'] != false,
        reason: map['reason'] as String? ?? '',
      );
    } on ApiException {
      return (needed: true, reason: '');
    }
  }

  /// What report generation for this session is doing; null when nothing
  /// is known (not started yet, or the server cannot be reached).
  Future<ReportProgress?> reportProgress(String sessionId) async {
    try {
      final body = await _send(
        () => _http.get(_uri('/api/sessions/$sessionId/report/progress')),
        timeout: const Duration(seconds: 5),
      );
      return ReportProgress.fromJson(body as Map<String, dynamic>);
    } on ApiException {
      return null;
    }
  }

  Uri reportPdfUrl(String sessionId) =>
      _uri('/api/sessions/$sessionId/report.pdf');

  /// [channel] is `sms` or `email`.
  Future<void> sendReport(String sessionId, String channel) => _send(
    () => _http.post(
      _uri('/api/sessions/$sessionId/report/send'),
      headers: _headers(json: true),
      body: jsonEncode({'channel': channel}),
    ),
    timeout: const Duration(seconds: 40),
  );

  Uri get voiceSocketUrl =>
      Uri.parse('${base.replaceFirst('http', 'ws')}/ws/voice').replace(
        queryParameters: previewTenantId != null
            ? {'tenant': previewTenantId!, 'admin': previewAdminKey!}
            : kioskKey.isEmpty
            ? null
            : {'key': kioskKey},
      );

  // --- Accounts ----------------------------------------------------------

  /// Signs in. Returns `{user, token}`.
  Future<Map<String, dynamic>> login(String email, String password) async =>
      await _send(
            () => _http.post(
              _uri('/api/auth/login'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({'email': email, 'password': password}),
            ),
          )
          as Map<String, dynamic>;

  /// Creates an account. `token` is null when the account still has to be
  /// approved by an administrator.
  Future<Map<String, dynamic>> register(
    String name,
    String email,
    String password,
  ) async =>
      await _send(
            () => _http.post(
              _uri('/api/auth/register'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({
                'name': name,
                'email': email,
                'password': password,
              }),
            ),
          )
          as Map<String, dynamic>;

  /// The user a stored session token belongs to; throws when it has expired.
  Future<Map<String, dynamic>> currentUser(String token) async =>
      await adminGet(token, '/api/auth/me') as Map<String, dynamic>;

  Future<void> logout(String token) =>
      adminSend(token, 'POST', '/api/auth/logout');

  // --- Back office -------------------------------------------------------
  // Responses are used as decoded JSON: the back office mostly shows what
  // the server says, so typed models would add little.

  Future<dynamic> adminGet(
    String adminKey,
    String path, {
    Map<String, String>? query,
  }) => _send(
    () => _http.get(_uri(path, query), headers: _headers(adminKey: adminKey)),
  );

  Future<dynamic> adminSend(
    String adminKey,
    String method,
    String path, {
    Object? body,
    Duration timeout = const Duration(seconds: 30),
  }) => _send(() async {
    final request = http.Request(method, _uri(path))
      ..headers.addAll(_headers(adminKey: adminKey, json: body != null));
    if (body != null) request.body = jsonEncode(body);
    return http.Response.fromStream(await _http.send(request));
  }, timeout: timeout);

  /// Uploads a source file; the server plans it with the AI before replying.
  Future<dynamic> adminUpload(
    String adminKey,
    String path, {
    required String filename,
    required Stream<List<int>> bytes,
    required int length,
  }) async {
    final request = http.MultipartRequest('POST', _uri(path))
      ..headers.addAll(_headers(adminKey: adminKey))
      ..files.add(
        http.MultipartFile('file', bytes, length, filename: filename),
      );
    final http.Response response;
    try {
      response = await http.Response.fromStream(
        await _http.send(request),
      ).timeout(const Duration(minutes: 10));
    } catch (_) {
      throw ApiException(null, 'Cannot reach the Medora server at $base');
    }
    return _decode(response);
  }
}

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());
