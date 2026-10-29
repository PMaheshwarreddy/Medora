import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/strings.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../state/kiosk_context.dart';
import '../audio/audio_io.dart';
import '../band/band_service.dart';
import '../models/intake.dart';
import '../state/intake_controller.dart';

/// The connection to `/ws/voice`. Text frames are JSON, binary frames audio.
abstract class VoiceLink {
  Stream<dynamic> get incoming;
  void send(Object data);
  Future<void> close();
}

class _SocketLink implements VoiceLink {
  _SocketLink(Uri url) : _channel = WebSocketChannel.connect(url);

  final WebSocketChannel _channel;

  @override
  Stream<dynamic> get incoming => _channel.stream;

  @override
  void send(Object data) => _channel.sink.add(data);

  @override
  Future<void> close() => _channel.sink.close();
}

final voiceLinkFactoryProvider = Provider<VoiceLink Function()>(
  (ref) =>
      () => _SocketLink(ref.read(kioskApiProvider).voiceSocketUrl),
);

enum VoiceStatus {
  connecting,

  /// Conversation in progress.
  live,

  /// The server has no voice agent to offer.
  unavailable,
  error,

  /// Intake finished; move on to review.
  complete,
}

class TranscriptLine {
  const TranscriptLine({required this.fromPatient, required this.text});

  final bool fromPatient;
  final String text;
}

class VoiceState {
  const VoiceState({
    this.status = VoiceStatus.connecting,
    this.message,
    this.lines = const [],
    this.speaking = false,
    this.takingVitals = false,
    this.paused = false,
  });

  final VoiceStatus status;

  /// Why voice is unavailable or what went wrong.
  final String? message;
  final List<TranscriptLine> lines;

  /// Medora's voice is currently playing.
  final bool speaking;
  final bool takingVitals;

  /// Staff paused the conversation (noise, an interruption): the
  /// microphone is off and Medora is silent until it is resumed.
  final bool paused;

  VoiceState copyWith({
    VoiceStatus? status,
    String? message,
    List<TranscriptLine>? lines,
    bool? speaking,
    bool? takingVitals,
    bool? paused,
  }) => VoiceState(
    status: status ?? this.status,
    message: message ?? this.message,
    lines: lines ?? this.lines,
    speaking: speaking ?? this.speaking,
    takingVitals: takingVitals ?? this.takingVitals,
    paused: paused ?? this.paused,
  );
}

class VoiceController extends Notifier<VoiceState> {
  VoiceLink? _link;
  StreamSubscription<dynamic>? _incoming;
  Timer? _speakingPoll;
  Timer? _vitalsTimeout;
  bool _started = false;
  bool _closed = false;
  // Set once the agent has said the intake is finished: from then on the
  // server closing the line is the expected end, not a failure.
  bool _completing = false;
  // True while the last transcript line may still receive more words.
  bool _lineOpen = false;

  // Captured in build: ref cannot be read while the provider is disposing.
  late AudioIo _audio;

  @override
  VoiceState build() {
    _audio = ref.read(audioIoProvider);
    ref.onDispose(_shutdown);
    return const VoiceState();
  }

  void start() {
    if (_started) return;
    _started = true;
    final link = _link = ref.read(voiceLinkFactoryProvider)();
    _incoming = link.incoming.listen(
      _onMessage,
      onError: (_) {
        if (!_completing) _fail('Cannot reach the Medora server.');
      },
      onDone: () {
        // After "complete" the server ends the session at once, often while
        // Medora's last sentence is still playing: _finish carries on.
        if (_completing) return;
        if (state.status == VoiceStatus.connecting ||
            state.status == VoiceStatus.live) {
          _fail('The conversation was disconnected.');
        }
      },
    );
    final visit = ref.read(intakeProvider);
    final known = visit.patient.toVoiceFields();
    final language = ref.read(languageProvider);
    link.send(
      jsonEncode({
        'type': 'start',
        'smartBand': ref.read(kioskConfigProvider).smartBand,
        // Malayalam chosen on the welcome page: she greets in Malayalam.
        // Otherwise she greets in English and follows the patient's
        // language ('auto', answered with a 'language' event); a visit
        // already under way stays in its language.
        'language': language == AppLanguage.malayalam
            ? 'ml'
            : known.isEmpty
            ? 'auto'
            : 'en',
        // After a reload mid-visit: what was already said, so Dr. Medora
        // carries on instead of starting over, and the band is not shown
        // again if it already measured.
        if (known.isNotEmpty) 'known': known,
        if (visit.vitals.hasAny) 'vitalsTaken': true,
      }),
    );
  }

  void _onMessage(dynamic message) {
    if (_closed) return;
    if (message is List<int>) {
      // While paused, whatever Medora was still saying is not played.
      if (state.paused) return;
      _audio.play(message is Uint8List ? message : Uint8List.fromList(message));
      return;
    }
    if (message is! String) return;
    final Map<String, dynamic> event;
    try {
      event = jsonDecode(message) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    switch (event['type']) {
      case 'ready':
        _onReady();
      case 'unavailable':
        _end(VoiceStatus.unavailable, event['reason'] as String?);
      case 'error':
        _fail(event['message'] as String? ?? 'The voice agent stopped.');
      case 'transcript':
        if (state.paused) return;
        _appendTranscript(
          fromPatient: event['role'] == 'patient',
          text: event['text'] as String? ?? '',
        );
      case 'interrupted':
        // The patient spoke over Medora: stop her mid-sentence.
        _audio.flush();
        _lineOpen = false;
      case 'turn_complete':
        _lineOpen = false;
      case 'intake':
        ref
            .read(intakeProvider.notifier)
            .mergePatient(event['fields'] as Map<String, dynamic>);
      case 'language':
        // The patient's choice: the screen, and the report, follow it.
        final chosen = AppLanguage.values
            .where((l) => l.code == event['language'])
            .firstOrNull;
        if (chosen != null) ref.read(languageProvider.notifier).set(chosen);
      case 'request_vitals':
        _takeVitals();
      case 'vitals_skipped':
        ref
            .read(intakeProvider.notifier)
            .skipVitals(event['reason'] as String? ?? '');
      case 'complete':
        _completing = true;
        // Nothing the patient says now is used.
        _audio.stopMic();
        _finish();
    }
  }

  /// Opens the microphone and streams it to the agent. False when it
  /// could not be opened (the session has then failed).
  Future<bool> _openMic() async {
    try {
      await _audio.startMic((chunk) {
        // Nothing is sent while the vitals are being taken or while paused.
        if (!_closed && !state.takingVitals && !state.paused) {
          _link?.send(chunk);
        }
      });
    } on AudioException catch (e) {
      _fail(e.message);
      return false;
    }
    if (_closed) {
      _audio.stopMic();
      return false;
    }
    return true;
  }

  Future<void> _onReady() async {
    if (!await _openMic()) return;
    state = state.copyWith(status: VoiceStatus.live);
    _speakingPoll = Timer.periodic(const Duration(milliseconds: 150), (_) {
      final speaking = _audio.isPlaying;
      if (speaking != state.speaking) {
        state = state.copyWith(speaking: speaking);
      }
    });
  }

  void _appendTranscript({required bool fromPatient, required String text}) {
    if (text.isEmpty) return;
    final lines = [...state.lines];
    // Transcripts arrive a few words at a time; grow the current line until
    // the speaker changes or the turn ends.
    if (_lineOpen &&
        lines.isNotEmpty &&
        lines.last.fromPatient == fromPatient) {
      lines.last = TranscriptLine(
        fromPatient: fromPatient,
        text: lines.last.text + text,
      );
    } else {
      lines.add(
        TranscriptLine(fromPatient: fromPatient, text: text.trimLeft()),
      );
    }
    _lineOpen = true;
    state = state.copyWith(lines: lines);
  }

  /// Stops listening and silences Medora until [resume]: for noise, or
  /// someone interrupting the patient. The conversation stays open.
  void pause() {
    if (_closed ||
        state.status != VoiceStatus.live ||
        state.paused ||
        state.takingVitals) {
      return;
    }
    state = state.copyWith(paused: true, speaking: false);
    _audio.stopMic();
    _audio.flush();
    _lineOpen = false;
    _link?.send(jsonEncode({'type': 'pause'}));
  }

  /// Listens again; Medora repeats her last question.
  Future<void> resume() async {
    if (_closed || !state.paused) return;
    state = state.copyWith(paused: false);
    if (!await _openMic()) return;
    _link?.send(jsonEncode({'type': 'resume'}));
  }

  /// The agent asked for vitals. The screen shows the band panel; the
  /// patient starts the measurement with a tap and the panel reports back
  /// through [vitalsFinished].
  void _takeVitals() {
    if (!ref.read(bandServiceProvider).isAvailable) {
      _sendVitals(null);
      return;
    }
    // Already measured in this visit: answer at once, never show the band
    // a second time.
    final taken = ref.read(intakeProvider).vitals;
    if (taken.hasAny) {
      _link?.send(_vitalsMessage(taken));
      return;
    }
    state = state.copyWith(takingVitals: true);
    // The microphone is off while the band measures: nothing the patient
    // says then is recorded or sent. It comes back once the vitals are in.
    _audio.stopMic();
    // A patient who never starts the band must not leave the agent waiting.
    _vitalsTimeout = Timer(const Duration(minutes: 5), () => _sendVitals(null));
  }

  /// The band panel is done: with the readings, or null without any.
  void vitalsFinished(Vitals? vitals) {
    if (!state.takingVitals) return;
    if (vitals != null && vitals.hasAny) {
      ref.read(intakeProvider.notifier).setVitals(vitals);
    }
    _sendVitals(vitals != null && vitals.hasAny ? vitals : null);
  }

  /// Tells the agent how the measurement went so it can carry on.
  void _sendVitals(Vitals? vitals) {
    _vitalsTimeout?.cancel();
    if (_closed) return;
    final wasTaking = state.takingVitals;
    state = state.copyWith(takingVitals: false);
    if (wasTaking) _openMic();
    _link?.send(_vitalsMessage(vitals));
  }

  String _vitalsMessage(Vitals? vitals) => jsonEncode({
    'type': 'vitals',
    'captured': vitals != null,
    if (vitals != null) ...{
      'heartRate': vitals.heartRate,
      'spo2': vitals.spo2,
      'temperatureC': vitals.temperatureC,
      'systolic': vitals.systolic,
      'diastolic': vitals.diastolic,
    },
  });

  /// Lets Medora finish her closing sentence before leaving the screen.
  Future<void> _finish() async {
    final deadline = DateTime.now().add(const Duration(seconds: 15));
    while (!_closed && _audio.isPlaying && DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 150));
    }
    if (!_closed) _end(VoiceStatus.complete, null);
  }

  void _fail(String message) => _end(VoiceStatus.error, message);

  void _end(VoiceStatus status, String? message) {
    if (_closed) return;
    _shutdown();
    state = state.copyWith(
      status: status,
      message: message,
      speaking: false,
      takingVitals: false,
    );
  }

  void _shutdown() {
    if (_closed) return;
    _closed = true;
    _speakingPoll?.cancel();
    _vitalsTimeout?.cancel();
    _incoming?.cancel();
    _audio.stopMic();
    _audio.flush();
    _link?.close();
  }
}

final voiceControllerProvider =
    NotifierProvider.autoDispose<VoiceController, VoiceState>(
      VoiceController.new,
    );
