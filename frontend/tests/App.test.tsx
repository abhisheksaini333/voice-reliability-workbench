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
      vi
        .fn()
        .mockResolvedValue({
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
      vi
        .fn()
        .mockResolvedValue({
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
