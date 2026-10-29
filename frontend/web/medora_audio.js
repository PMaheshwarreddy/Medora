// Microphone capture and speech playback for the voice intake.
// Dart talks to this through `window.medoraAudio` (lib/audio/audio_io_web.dart).
//   capture:  PCM16 mono 16 kHz, delivered in 50 ms chunks
//   playback: PCM16 mono 24 kHz, queued gaplessly
(function () {
  const MIC_RATE = 16000;
  const PLAY_RATE = 24000;

  const WORKLET = `
    class MedoraMic extends AudioWorkletProcessor {
      constructor() {
        super();
        this.buf = new Int16Array(${MIC_RATE / 20});
        this.n = 0;
      }
      process(inputs) {
        const ch = inputs[0][0];
        if (!ch) return true;
        for (let i = 0; i < ch.length; i++) {
          const s = Math.max(-1, Math.min(1, ch[i]));
          this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
          if (this.n === this.buf.length) {
            this.port.postMessage(this.buf.buffer.slice(0));
            this.n = 0;
          }
        }
        return true;
      }
    }
    registerProcessor('medora-mic', MedoraMic);`;

  let micCtx = null;
  let micStream = null;
  let playCtx = null;
  let nextTime = 0;
  const sources = new Set();

  async function startMic(onChunk) {
    stopMic();
    // Echo cancellation keeps Medora's own voice out of the microphone, so
    // she does not interrupt herself.
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    micCtx = new AudioContext({ sampleRate: MIC_RATE });
    const url = URL.createObjectURL(
      new Blob([WORKLET], { type: 'application/javascript' }));
    try {
      await micCtx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const node = new AudioWorkletNode(micCtx, 'medora-mic');
    node.port.onmessage = (e) => onChunk(e.data);
    // The graph only runs when it reaches the destination; the muted gain
    // keeps the microphone from being played back.
    const mute = micCtx.createGain();
    mute.gain.value = 0;
    micCtx.createMediaStreamSource(micStream).connect(node);
    node.connect(mute).connect(micCtx.destination);
    await micCtx.resume();
  }

  function stopMic() {
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    if (micCtx) micCtx.close();
    micStream = null;
    micCtx = null;
  }

  function play(arrayBuffer) {
    const pcm = new Int16Array(arrayBuffer, 0, arrayBuffer.byteLength >> 1);
    if (pcm.length === 0) return;
    if (!playCtx) playCtx = new AudioContext();
    if (playCtx.state === 'suspended') playCtx.resume();
    const buffer = playCtx.createBuffer(1, pcm.length, PLAY_RATE);
    const out = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) out[i] = pcm[i] / 0x8000;
    const source = playCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(playCtx.destination);
    const startAt = Math.max(nextTime, playCtx.currentTime + 0.03);
    source.start(startAt);
    nextTime = startAt + buffer.duration;
    sources.add(source);
    source.onended = () => sources.delete(source);
  }

  // Drops everything queued: used when the patient talks over Medora.
  function flush() {
    sources.forEach((s) => {
      s.onended = null;
      try { s.stop(); } catch (_) {}
    });
    sources.clear();
    nextTime = 0;
  }

  function isPlaying() {
    return sources.size > 0;
  }

  window.medoraAudio = { startMic, stopMic, play, flush, isPlaying };
})();
