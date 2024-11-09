import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { App } from "../src/App";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("voice workspace consent and operator boundary", () => {
  it("does not request microphone access when opening the workspace", async () => {
    const microphone = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: microphone },
      configurable: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ diagnostics: false }),
      })
    );
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Ready when you are." })
    ).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "Create a conversation",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);
    await waitFor(() =>
      expect(screen.getByText("Local services ready")).toBeTruthy()
    );
    expect(microphone).not.toHaveBeenCalled();
  });
  it("requires the separate operator key before loading handoff context", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ diagnostics: false }),
      })
    );
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Operator review/ }));
    expect(screen.getByLabelText("Operator key")).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "Load conversations",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);
  });
});

it("clears the transient draft when a turn is interrupted", async () => {
  let live: any;
  class Socket {
    static OPEN = 1;
    readyState = 1;
    onmessage: any;
    onclose: any;
    onopen: any;
    constructor() {
      live = this;
    }
    send() {}
    close() {}
  }
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(async (path: string) => ({
        ok: true,
        json: async () =>
          path === "/api/sessions"
            ? { id: "session", token: "session-token" }
            : path.startsWith("/api/sessions/")
            ? { session: {}, turns: [], events: [] }
            : { diagnostics: false },
      }))
  );
  render(<App />);
  fireEvent.change(screen.getByLabelText("Workspace key", { exact: true }), {
    target: { value: "w".repeat(40) },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Create a conversation" })
  );
  await waitFor(() => expect(live).toBeTruthy());
  const { act } = await import("@testing-library/react");
  await act(async () => {
    live.onmessage({
      data: JSON.stringify({ type: "transcript", text: "A cancelled draft." }),
    });
  });
  expect(screen.getByText("CURRENT TURN")).toBeTruthy();
  await act(async () => {
    live.onmessage({ data: JSON.stringify({ type: "stop_audio", epoch: 3 }) });
  });
  expect(screen.queryByText("CURRENT TURN")).toBeNull();
});
