import 'dart:typed_data';

import 'audio_io.dart';

/// Used off the web (tests, future native builds until they get their own).
class _NoAudio implements AudioIo {
  @override
  Future<void> startMic(void Function(Uint8List chunk) onChunk) async =>
      throw AudioException('Voice is only available in the browser.');

  @override
  void stopMic() {}

  @override
  void play(Uint8List pcm) {}

  @override
  void flush() {}

  @override
  bool get isPlaying => false;
}

AudioIo createAudioIo() => _NoAudio();
