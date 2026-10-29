import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'audio_io_stub.dart' if (dart.library.js_interop) 'audio_io_web.dart';

class AudioException implements Exception {
  AudioException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// Microphone in, speech out. Capture is PCM16 mono 16 kHz; playback is
/// PCM16 mono 24 kHz.
abstract class AudioIo {
  /// Throws [AudioException] when the microphone cannot be opened.
  Future<void> startMic(void Function(Uint8List chunk) onChunk);
  void stopMic();

  void play(Uint8List pcm);

  /// Drops queued speech immediately.
  void flush();
  bool get isPlaying;
}

final audioIoProvider = Provider<AudioIo>((ref) => createAudioIo());
