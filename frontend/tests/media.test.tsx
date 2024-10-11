import { describe, it, expect } from "vitest";
// @ts-ignore Worklet module is shared directly with the browser audio thread.
import { PCMFramer } from "../public/pcm.js";
import { Playback } from "../src/media";

describe("actual microphone framing", () => {
  it("retains a continuous sample clock across uneven 44.1k and 48k blocks", () => {
    for (const rate of [44100, 48000]) {
      const packets: ArrayBuffer[] = [];
      const framer = new PCMFramer(rate, (packet: ArrayBuffer) =>
        packets.push(packet)
      );
      for (let offset = 0; offset < rate; offset += 128)
        framer.push(new Float32Array(Math.min(128, rate - offset)).fill(0.25));
      expect(packets.length).toBe(50);
      expect(packets.every((p) => p.byteLength === 640)).toBe(true);
      expect(new DataView(packets[0]).getInt16(0, true)).toBe(8192);
    }
  });
});

describe("playback fencing", () => {
  function setup() {
    const nodes: any[] = [];
    const events: any[] = [];
    const context: any = {
      currentTime: 0,
      state: "running",
      createBuffer: () => ({ getChannelData: () => new Float32Array(8) }),
      createBufferSource: () => {
        const node: any = {
          connect() {},
          start() {},
          stop() {
            node.stopped = true;
          },
          disconnect() {},
        };
        nodes.push(node);
        return node;
      },
      destination: {},
    };
    return {
      nodes,
      events,
      player: new Playback(context, (e) => events.push(e)),
    };
  }
  it("stops every scheduled source and rejects old epoch audio after interruption", () => {
    const { nodes, player, events } = setup();
    player.reset(2);
    player.enqueue({
      epoch: 2,
      sequence: 0,
      sample_rate: 22050,
      pcm: btoa("\0".repeat(16)),
    });
    player.invalidate();
    expect(nodes[0].stopped).toBe(true);
    expect(
      player.enqueue({
        epoch: 2,
        sequence: 1,
        sample_rate: 22050,
        pcm: btoa("\0".repeat(16)),
      })
    ).toBe(false);
    player.reset(3);
    nodes[0].onended();
    expect(events.some((e) => e.type === "ack")).toBe(false);
  });
  it("rejects duplicate sequence and more than four unacknowledged chunks", () => {
    const { player } = setup();
    player.reset(1);
    const event = {
      epoch: 1,
      sequence: 0,
      sample_rate: 22050,
      pcm: btoa("\0".repeat(16)),
    };
    player.enqueue(event);
    expect(() => player.enqueue(event)).toThrow();
    for (let sequence = 1; sequence < 4; sequence++)
      player.enqueue({ ...event, sequence });
    expect(() => player.enqueue({ ...event, sequence: 4 })).toThrow();
    player.invalidate();
  });
});
