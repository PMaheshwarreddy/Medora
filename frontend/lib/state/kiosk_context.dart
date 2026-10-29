import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../config/app_config.dart';

/// A client's kiosk opened from the back office to see what its patients see.
class KioskPreview {
  const KioskPreview({
    required this.clientName,
    required this.api,
    required this.config,
  });

  final String clientName;
  final ApiClient api;
  final AppConfig config;
}

class KioskPreviewController extends Notifier<KioskPreview?> {
  @override
  KioskPreview? build() => null;

  void start(KioskPreview preview) => state = preview;

  void stop() => state = null;
}

/// Null on a real kiosk; set while the back office previews a client.
final kioskPreviewProvider =
    NotifierProvider<KioskPreviewController, KioskPreview?>(
      KioskPreviewController.new,
    );

/// The API client the kiosk screens talk through: the previewed client's
/// while previewing, this kiosk's own otherwise.
final kioskApiProvider = Provider<ApiClient>(
  (ref) => ref.watch(kioskPreviewProvider)?.api ?? ref.watch(apiClientProvider),
);

/// The feature switches the kiosk screens obey.
final kioskConfigProvider = Provider<AppConfig>(
  (ref) =>
      ref.watch(kioskPreviewProvider)?.config ?? ref.watch(appConfigProvider),
);
