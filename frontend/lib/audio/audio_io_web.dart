import 'dart:js_interop';
import 'dart:typed_data';

import 'audio_io.dart';

/// Bindings to `web/medora_audio.js`.
@JS('medoraAudio')
external _MedoraAudio? get _audio;

extension type _MedoraAudio._(JSObject _) implements JSObject {
  external JSPromise<JSAny?> startMic(JSFunction onChunk);
  external void stopMic();
  external void play(JSArrayBuffer pcm);
  external void flush();
  external bool isPlaying();
}

class _WebAudio implements AudioIo {
  @override
  Future<void> startMic(void Function(Uint8List chunk) onChunk) async {
    final audio = _audio;
    if (audio == null) throw AudioException('The audio module did not load.');
    try {
      await audio
          .startMic(
            ((JSArrayBuffer data) => onChunk(data.toDart.asUint8List())).toJS,
          )
          .toDart;
    } catch (_) {
      throw AudioException(
        'Medora needs the microphone. Allow microphone access and try again.',
      );
    }
  }

  @override
  void stopMic() => _audio?.stopMic();

  @override
  void play(Uint8List pcm) {
    // Copy: the chunk may be a view into a larger buffer.
    _audio?.play(Uint8List.fromList(pcm).buffer.toJS);
  }

  @override
  void flush() => _audio?.flush();

  @override
  bool get isPlaying => _audio?.isPlaying() ?? false;
}

AudioIo createAudioIo() => _WebAudio();
