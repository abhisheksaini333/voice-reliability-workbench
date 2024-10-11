import { PCMFramer } from "./pcm.js";
class VoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.framer = new PCMFramer(sampleRate, (pcm) => {
      this.port.postMessage({ pcm }, [pcm]);
    });
  }
  process(inputs) {
    const samples = inputs[0]?.[0];
    if (samples) this.framer.push(samples);
    return true;
  }
}
registerProcessor("voice-capture", VoiceCapture);
