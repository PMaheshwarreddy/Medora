import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:medora/audio/audio_io.dart';
import 'package:medora/band/band_service.dart';
import 'package:medora/band/ble/ble_central.dart';
import 'package:medora/band/drivers/qring/qring_band.dart';
import 'package:medora/l10n/strings.dart';
import 'package:medora/models/intake.dart';
import 'package:medora/state/intake_controller.dart';
import 'package:medora/voice/voice_controller.dart';

class FakeLink implements VoiceLink {
  final server = StreamController<dynamic>();
  final sent = <Object>[];
  bool closed = false;

  @override
  Stream<dynamic> get incoming => server.stream;

  @override
  void send(Object data) => sent.add(data);

  @override
  Future<void> close() async => closed = true;

  void event(Map<String, dynamic> e) => server.add(jsonEncode(e));

  List<Map<String, dynamic>> get sentJson => [
    for (final s in sent.whereType<String>())
      jsonDecode(s) as Map<String, dynamic>,
  ];
}

class FakeAudio implements AudioIo {
  void Function(Uint8List)? mic;
  final played = <Uint8List>[];
  int flushes = 0;
  bool failMic = false;

  @override
  Future<void> startMic(void Function(Uint8List chunk) onChunk) async {
    if (failMic) throw AudioException('no mic');
    mic = onChunk;
  }

  @override
  void stopMic() => mic = null;

  @override
  void play(Uint8List pcm) => played.add(pcm);

  @override
  void flush() => flushes++;

  // Medora still speaking.
  bool playing = false;

  @override
  bool get isPlaying => playing;
}

class FakeBand implements BandService {
  @override
  String get deviceNoun => 'ring';

  @override
  String get wearInstruction => 'Put it on.';

  @override
  List<VitalSign> get measures => const [VitalSign.heartRate, VitalSign.spo2];

  @override
  bool get isAvailable => true;

  @override
  String get unavailableReason => '';

  @override
  Stream<BandStatus> measure() => const Stream.empty();
}

Future<void> settle() => Future<void>.delayed(Duration.zero);

void main() {
  late FakeLink link;
  late FakeAudio audio;

  ProviderContainer start({BandService? band}) {
    link = FakeLink();
    audio = FakeAudio();
    final container = ProviderContainer(
      overrides: [
        voiceLinkFactoryProvider.overrideWithValue(() => link),
        audioIoProvider.overrideWithValue(audio),
        if (band != null) bandServiceProvider.overrideWithValue(band),
      ],
    );
    addTearDown(container.dispose);
    // Keeps the auto-dispose controller alive for the test.
    container.listen(voiceControllerProvider, (_, _) {});
    container.read(voiceControllerProvider.notifier).start();
    return container;
  }

  VoiceState state(ProviderContainer c) => c.read(voiceControllerProvider);

  test('goes live, streams the microphone and plays replies', () async {
    final c = start();
    expect(link.sentJson.single, {
      'type': 'start',
      'smartBand': true,
      'language': 'auto',
    });
    expect(state(c).status, VoiceStatus.connecting);

    link.event({'type': 'ready'});
    await settle();
    expect(state(c).status, VoiceStatus.live);

    audio.mic!(Uint8List.fromList([1, 2, 3, 4]));
    expect(link.sent.last, [1, 2, 3, 4]);

    link.server.add(Uint8List.fromList([9, 9]));
    await settle();
    expect(audio.played.single, [9, 9]);
  });

  test('the patient chooses the language by voice', () async {
    final c = start();
    link.event({'type': 'ready'});
    link.event({'type': 'language', 'language': 'ml'});
    await settle();
    expect(c.read(languageProvider), AppLanguage.malayalam);
    link.event({'type': 'language', 'language': 'en'});
    await settle();
    expect(c.read(languageProvider), AppLanguage.english);
  });

  test('pause silences everything until resume', () async {
    final c = start();
    link.event({'type': 'ready'});
    await settle();

    c.read(voiceControllerProvider.notifier).pause();
    expect(state(c).paused, isTrue);
    expect(audio.mic, isNull); // microphone off
    expect(audio.flushes, 1); // Medora stopped mid-sentence
    expect(link.sentJson.last, {'type': 'pause'});

    // What the agent still sends while paused is neither played nor shown.
    link.server.add(Uint8List.fromList([7, 7]));
    link.event({'type': 'transcript', 'role': 'medora', 'text': 'Hello?'});
    await settle();
    expect(audio.played, isEmpty);
    expect(state(c).lines, isEmpty);

    await c.read(voiceControllerProvider.notifier).resume();
    expect(state(c).paused, isFalse);
    expect(audio.mic, isNotNull);
    expect(link.sentJson.last, {'type': 'resume'});
    audio.mic!(Uint8List.fromList([5]));
    expect(link.sent.last, [5]);
  });

  test('the intake keeps allergies and the pregnancy answer', () async {
    final c = start();
    link.event({'type': 'ready'});
    link.event({
      'type': 'intake',
      'fields': {'allergies': 'penicillin', 'pregnancy': 'no'},
    });
    await settle();
    final patient = c.read(intakeProvider).patient;
    expect(patient.allergies, 'penicillin');
    expect(patient.pregnancy, 'no');
  });

  test('builds transcript lines and fills in the intake', () async {
    final c = start();
    link.event({'type': 'ready'});
    link.event({'type': 'transcript', 'role': 'medora', 'text': 'How can I '});
    link.event({'type': 'transcript', 'role': 'medora', 'text': 'help you?'});
    link.event({'type': 'turn_complete'});
    link.event({'type': 'transcript', 'role': 'patient', 'text': ' I have a'});
    link.event({'type': 'transcript', 'role': 'patient', 'text': ' fever'});
    link.event({
      'type': 'intake',
      'fields': {'name': 'Asha Rao', 'age': 34, 'gender': 'female'},
    });
    link.event({
      'type': 'intake',
      'fields': {'symptoms': 'fever'},
    });
    await settle();

    expect(
      [for (final l in state(c).lines) (l.fromPatient, l.text)],
      [(false, 'How can I help you?'), (true, 'I have a fever')],
    );
    final patient = c.read(intakeProvider).patient;
    expect(patient.name, 'Asha Rao');
    expect(patient.age, 34);
    expect(patient.gender, Gender.female);
    expect(patient.symptoms, 'fever');
  });

  test('barge-in stops playback', () async {
    start();
    link.event({'type': 'ready'});
    link.event({'type': 'interrupted'});
    await settle();
    expect(audio.flushes, 1);
  });

  test('without a band the agent is told vitals are unavailable', () async {
    // The real band on a machine without Bluetooth (the test VM).
    final c = start(band: QRingBand(createBleCentral()));
    link.event({'type': 'ready'});
    link.event({'type': 'request_vitals'});
    await settle();
    expect(link.sentJson.last, {'type': 'vitals', 'captured': false});
    expect(state(c).takingVitals, isFalse);
  });

  test('with a band the readings are stored and reported', () async {
    final c = start(band: FakeBand());
    link.event({'type': 'ready'});
    link.event({'type': 'request_vitals'});
    await settle();
    // The screen now shows the band panel; the agent waits for it.
    expect(state(c).takingVitals, isTrue);
    // The microphone is off while the band measures.
    expect(audio.mic, isNull);
    expect(link.sentJson.where((m) => m['type'] == 'vitals'), isEmpty);

    // A ring without blood pressure or temperature still reports.
    c
        .read(voiceControllerProvider.notifier)
        .vitalsFinished(const Vitals(heartRate: 80, spo2: 98));
    await settle();
    expect(state(c).takingVitals, isFalse);
    expect(link.sentJson.last['captured'], isTrue);
    expect(link.sentJson.last['spo2'], 98);
    expect(link.sentJson.last['systolic'], isNull);
    // And back on afterwards, for the rest of the conversation.
    expect(audio.mic, isNotNull);
  });

  test('a patient who skips the band is reported as no vitals', () async {
    final c = start(band: FakeBand());
    link.event({'type': 'ready'});
    link.event({'type': 'request_vitals'});
    await settle();
    c.read(voiceControllerProvider.notifier).vitalsFinished(null);
    await settle();
    expect(link.sentJson.last, {'type': 'vitals', 'captured': false});
    expect(state(c).takingVitals, isFalse);
  });

  test('complete ends the session and releases the microphone', () async {
    final c = start();
    link.event({'type': 'ready'});
    link.event({'type': 'complete'});
    await settle();
    await settle();
    expect(state(c).status, VoiceStatus.complete);
    expect(audio.mic, isNull);
    expect(link.closed, isTrue);
  });

  test('unavailable and microphone failures are reported', () async {
    var c = start();
    link.event({'type': 'unavailable', 'reason': 'Not set up'});
    await settle();
    expect(state(c).status, VoiceStatus.unavailable);
    expect(state(c).message, 'Not set up');

    c = start();
    audio.failMic = true;
    link.event({'type': 'ready'});
    await settle();
    expect(state(c).status, VoiceStatus.error);
    expect(state(c).message, 'no mic');
  });

  test('a dropped connection is an error', () async {
    final c = start();
    link.event({'type': 'ready'});
    await settle();
    await link.server.close();
    await settle();
    expect(state(c).status, VoiceStatus.error);
  });

  test('the server closing right after "complete" is not a failure', () async {
    final c = start();
    link.event({'type': 'ready'});
    await settle();
    // Medora is still saying goodbye when the server ends the session.
    audio.playing = true;
    link.event({'type': 'complete'});
    await settle();
    await link.server.close();
    await settle();
    expect(state(c).status, isNot(VoiceStatus.error));
    expect(audio.mic, isNull); // nothing more is recorded
    audio.playing = false;
    await Future<void>.delayed(const Duration(milliseconds: 300));
    expect(state(c).status, VoiceStatus.complete);
  });

  test('a disconnect mid-conversation is still a failure', () async {
    final c = start();
    link.event({'type': 'ready'});
    await settle();
    await link.server.close();
    await settle();
    expect(state(c).status, VoiceStatus.error);
  });

  test('vitals the complaint does not need are noted, not taken', () async {
    final c = start(band: FakeBand());
    link.event({'type': 'ready'});
    link.event({
      'type': 'vitals_skipped',
      'reason': 'Your back pain does not need a heart or oxygen check.',
    });
    await settle();
    expect(
      c.read(intakeProvider).vitalsNotNeeded,
      'Your back pain does not need a heart or oxygen check.',
    );
    expect(state(c).takingVitals, isFalse);
  });

  test('vitals are taken once: a second request is answered at once', () async {
    final c = start(band: FakeBand());
    link.event({'type': 'ready'});
    link.event({'type': 'request_vitals'});
    await settle();
    c
        .read(voiceControllerProvider.notifier)
        .vitalsFinished(const Vitals(heartRate: 72, spo2: 98));
    await settle();
    final answers = link.sentJson.where((m) => m['type'] == 'vitals').length;

    link.event({'type': 'request_vitals'});
    await settle();
    // No band panel again; the same readings go straight back.
    expect(state(c).takingVitals, isFalse);
    expect(
      link.sentJson.where((m) => m['type'] == 'vitals').length,
      answers + 1,
    );
    expect(link.sentJson.last['heartRate'], 72);
  });
}
