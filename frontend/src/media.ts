export type Control = Record<string, unknown>;
export type AudioPacket = {
  epoch: number;
  sequence: number;
  sample_rate: number;
  pcm: string;
};

export class Capture {
  private stream?: MediaStream;
  private source?: MediaStreamAudioSourceNode;
  private node?: AudioWorkletNode;
  private generation = 0;
  frames = 0;
  async start(
    context: AudioContext,
    send: (packet: ArrayBuffer) => void,
    begin: () => void,
    level: (value: number) => void
  ) {
    this.stop();
    const generation = this.generation;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    if (generation !== this.generation) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    this.stream = stream;
    try {
      await context.audioWorklet.addModule("/capture.js");
      if (generation !== this.generation) return;
      this.node = new AudioWorkletNode(context, "voice-capture");
      this.source = context.createMediaStreamSource(stream);
      this.frames = 0;
      this.node.port.onmessage = ({ data }) => {
        if (
          generation !== this.generation ||
          !(data.pcm instanceof ArrayBuffer) ||
          data.pcm.byteLength !== 640
        )
          return;
        const packet = new ArrayBuffer(648),
          view = new DataView(packet);
        view.setUint32(0, this.frames);
        view.setUint32(4, this.frames * 320);
        new Uint8Array(packet, 8).set(new Uint8Array(data.pcm));
        this.frames++;
        let energy = 0;
        const samples = new DataView(data.pcm);
        for (let i = 0; i < 320; i++)
          energy += (samples.getInt16(i * 2, true) / 32768) ** 2;
        level(Math.sqrt(energy / 320));
        send(packet);
      };
      begin();
      this.source.connect(this.node);
      // Silent worklet output keeps capture rendering active without mic feedback.
      this.node.connect(context.destination);
    } catch (error) {
      this.stop();
      throw error;
    }
  }
  stop() {
    this.generation++;
    this.node?.port.close();
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.node = undefined;
    this.source = undefined;
    this.stream = undefined;
  }
}

export class Playback {
  epoch = 0;
  private blocked = true;
  private sequence = 0;
  private nextTime = 0;
  private nodes = new Map<number, AudioBufferSourceNode>();
  private startedTimer?: ReturnType<typeof setTimeout>;
  constructor(
    private context: AudioContext,
    private send: (control: Control) => void
  ) {}
  invalidate() {
    this.blocked = true;
    if (this.startedTimer) clearTimeout(this.startedTimer);
    this.startedTimer = undefined;
    for (const node of this.nodes.values()) {
      node.stop();
      node.disconnect();
    }
    this.nodes.clear();
    this.nextTime = 0;
  }
  reset(epoch: number) {
    if (!Number.isSafeInteger(epoch) || epoch < this.epoch) return;
    this.invalidate();
    this.epoch = epoch;
    this.sequence = 0;
    this.blocked = false;
  }
  enqueue(packet: AudioPacket) {
    if (this.blocked || packet.epoch !== this.epoch) return false;
    if (
      packet.sequence !== this.sequence ||
      this.nodes.size >= 4 ||
      packet.sample_rate !== 22050 ||
      typeof packet.pcm !== "string" ||
      packet.pcm.length > 15000
    )
      throw new Error("Invalid audio delivery");
    const raw = atob(packet.pcm);
    if (!raw.length || raw.length % 2 || raw.length > 11024)
      throw new Error("Invalid audio chunk");
    const bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0)),
      view = new DataView(bytes.buffer);
    const buffer = this.context.createBuffer(1, raw.length / 2, 22050),
      samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++)
      samples[i] = view.getInt16(i * 2, true) / 32768;
    const node = this.context.createBufferSource();
    node.buffer = buffer;
    node.connect(this.context.destination);
    const start = Math.max(this.context.currentTime + 0.02, this.nextTime);
    this.nextTime = start + raw.length / 2 / 22050;
    const epoch = this.epoch;
    this.nodes.set(packet.sequence, node);
    this.sequence++;
    node.onended = () => {
      node.disconnect();
      if (
        epoch === this.epoch &&
        !this.blocked &&
        this.nodes.get(packet.sequence) === node
      ) {
        this.nodes.delete(packet.sequence);
        this.send({ type: "ack", epoch, sequence: packet.sequence });
      }
    };
    node.start(start);
    if (packet.sequence === 0)
      this.startedTimer = setTimeout(() => {
        if (
          epoch === this.epoch &&
          !this.blocked &&
          this.context.state === "running"
        )
          this.send({ type: "playback_started", epoch });
      }, Math.max(0, (start - this.context.currentTime) * 1000));
    return true;
  }
}
