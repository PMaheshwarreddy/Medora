import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'kiosk_context.dart';
import '../api/api_client.dart';
import '../models/intake.dart';

/// The server's live capabilities, refreshed every few seconds so the kiosk
/// follows the connection: offline it stops offering what needs the internet,
/// and offers it again when the connection returns.
final serviceStatusProvider = StreamProvider<ServiceStatus>((ref) async* {
  final api = ref.watch(kioskApiProvider);
  while (true) {
    try {
      yield await api.status();
    } on ApiException {
      yield const ServiceStatus.unreachable();
    }
    await Future<void>.delayed(const Duration(seconds: 8));
  }
});
