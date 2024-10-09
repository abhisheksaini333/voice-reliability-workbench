// Bounded box averaging resampler for speech capture, followed by fixed PCM16 frames.
// This is a transport resampler, not a studio-quality anti-aliasing filter.
export class PCMFramer {
  constructor(inputRate, emit) {
    if (!Number.isFinite(inputRate) || inputRate < 16000 || inputRate > 192000) throw new Error('Unsupported input rate');
    this.ratio = inputRate / 16000;
    this.emit = emit;
    this.remaining = this.ratio;
    this.sum = 0;
    this.packet = new ArrayBuffer(640);
    this.view = new DataView(this.packet);
    this.offset = 0;
  }
  push(samples) {
    for (const input of samples) {
      let available = 1;
      const value = Math.max(-1, Math.min(1, Number.isFinite(input) ? input : 0));
      while (available > 1e-9) {
        const used = Math.min(available, this.remaining);
        this.sum += value * used;
        this.remaining -= used;
        available -= used;
        if (this.remaining < 1e-9) {
          this.view.setInt16(this.offset * 2, Math.max(-32768,Math.min(32767,Math.round(this.sum / this.ratio * 32768))), true);
          this.offset++;
          this.sum = 0;
          this.remaining = this.ratio;
          if (this.offset === 320) {
            this.emit(this.packet);
            this.packet = new ArrayBuffer(640);
            this.view = new DataView(this.packet);
            this.offset = 0;
          }
        }
      }
    }
  }
}
