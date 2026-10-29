import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../api/api_client.dart';

/// Per-client feature switches. Managed from the back office and served by
/// the API; `medora_config.json` next to `index.html` is the fallback when
/// the server cannot be reached.
class AppConfig {
  const AppConfig({
    this.voiceIntake = true,
    this.manualIntake = true,
    this.smartBand = true,
    this.doctorReview = true,
  });

  final bool voiceIntake;
  final bool manualIntake;
  final bool smartBand;

  /// A doctor reviews every report in the doctor portal: the kiosk shows a
  /// preliminary report and a code for the patient's final one.
  final bool doctorReview;

  factory AppConfig.fromJson(Map<String, dynamic> json) {
    final voice = json['voiceIntake'] as bool? ?? true;
    final manual = json['manualIntake'] as bool? ?? true;
    return AppConfig(
      voiceIntake: voice,
      // The patient always needs one way in: with both switched off, fall
      // back to the form.
      manualIntake: manual || !voice,
      smartBand: json['smartBand'] as bool? ?? true,
      doctorReview: json['doctorReview'] as bool? ?? true,
    );
  }

  Map<String, dynamic> toJson() => {
    'voiceIntake': voiceIntake,
    'manualIntake': manualIntake,
    'smartBand': smartBand,
    'doctorReview': doctorReview,
  };

  AppConfig copyWith({
    bool? voiceIntake,
    bool? manualIntake,
    bool? smartBand,
    bool? doctorReview,
  }) => AppConfig(
    voiceIntake: voiceIntake ?? this.voiceIntake,
    manualIntake: manualIntake ?? this.manualIntake,
    smartBand: smartBand ?? this.smartBand,
    doctorReview: doctorReview ?? this.doctorReview,
  );

  /// The file next to `index.html`. Besides fallback switches it carries
  /// `kioskKey`, which ties this kiosk to its client.
  static Future<Map<String, dynamic>> loadLocalFile() async {
    try {
      final response = await http
          .get(Uri.base.resolve('medora_config.json'))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return const {};
  }

  /// Server first, then the local file, then everything enabled.
  static Future<AppConfig> load(
    ApiClient api,
    Map<String, dynamic> file,
  ) async {
    try {
      return await api.fetchConfig().timeout(const Duration(seconds: 3));
    } catch (_) {
      return AppConfig.fromJson(file);
    }
  }
}

/// Overridden in `main` with the loaded config.
final appConfigProvider = Provider<AppConfig>((ref) => const AppConfig());
