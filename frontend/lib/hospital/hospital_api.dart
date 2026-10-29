import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../api/api_client.dart' show ApiException, medoraApiBase;

/// The hospital portal's own connection to `/api/hospital/...`, with the
/// hospital sign-in token (never the company back office's).
class HospitalClient {
  HospitalClient({http.Client? client, String? base})
    : _http = client ?? http.Client(),
      base = base ?? medoraApiBase;

  final http.Client _http;
  final String base;

  Uri uri(String path, [Map<String, String>? query]) => Uri.parse(
    '$base$path',
  ).replace(queryParameters: (query == null || query.isEmpty) ? null : query);

  Future<dynamic> send(
    String method,
    String path, {
    String? token,
    Object? body,
    Map<String, String>? query,
  }) async {
    final http.Response response;
    try {
      final request = http.Request(method, uri(path, query))
        ..headers.addAll({
          'X-Hospital-Token': ?token,
          if (body != null) 'Content-Type': 'application/json',
        });
      if (body != null) request.body = jsonEncode(body);
      response = await http.Response.fromStream(
        await _http.send(request),
      ).timeout(const Duration(seconds: 30));
    } catch (_) {
      throw ApiException(null, 'Cannot reach the Medora server at $base');
    }
    final decoded = response.body.isEmpty
        ? null
        : jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode >= 400) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw ApiException(
        response.statusCode,
        detail is String ? detail : 'Request failed (${response.statusCode})',
      );
    }
    return decoded;
  }

  Future<Map<String, dynamic>> login(String email, String password) async =>
      await send(
            'POST',
            '/api/hospital/auth/login',
            body: {'email': email, 'password': password},
          )
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> me(String token) async =>
      await send('GET', '/api/hospital/auth/me', token: token)
          as Map<String, dynamic>;
}

final hospitalClientProvider = Provider<HospitalClient>(
  (ref) => HospitalClient(),
);

/// The API as seen by the signed-in hospital person.
class HospitalApi {
  HospitalApi(this._client, this.token, this.user, this.hospital);

  final HospitalClient _client;
  final String token;

  /// `id`, `name`, `email`, `role`, `mustChangePassword`...
  final Map<String, dynamic> user;

  /// `id`, `name`, `logo`.
  final Map<String, dynamic> hospital;

  String get base => _client.base;

  bool get isAdmin => user['role'] == 'hospital_admin';

  HospitalApi copyWith({
    Map<String, dynamic>? user,
    Map<String, dynamic>? hospital,
  }) =>
      HospitalApi(_client, token, user ?? this.user, hospital ?? this.hospital);

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _client.send('GET', '/api/hospital$path', token: token, query: query);

  Future<dynamic> send(String method, String path, {Object? body}) =>
      _client.send(method, '/api/hospital$path', token: token, body: body);

  /// Any API path with this sign-in (the doctor portal's `/api/doctor`).
  Future<dynamic> raw(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
  }) => _client.send(method, path, token: token, body: body, query: query);

  Uri uri(String path) => _client.uri(path);

  /// The patient's PDF, for the visits page.
  Uri reportPdf(String visitId) =>
      _client.uri('/api/sessions/$visitId/report.pdf');
}
