import React, { useEffect, useRef, useState } from "react";
import { Capture, Playback, Control } from "./media";
import "./style.css";

type Session = { id: string; token: string };
type State = {
  phase: string;
  epoch: number;
  connection: number;
  recording: boolean;
  connected: boolean;
};
type Turn = {
  epoch: number;
  state: string;
  transcript: string;
  reply: string;
  timings: Record<string, number>;
  error_code?: string;
};
type Detail = {
  session: Record<string, any>;
  turns: Turn[];
  events: Array<{
    id: number;
    kind: string;
    epoch: number;
    detail: Record<string, any>;
  }>;
};
const initial: State = {
  phase: "idle",
  epoch: 0,
  connection: 0,
  recording: false,
  connected: false,
};
const stages = ["stt", "model", "tts"];
const stageNames: Record<string, string> = {
  stt: "Recognize speech",
  model: "Compose a response",
  tts: "Synthesize audio",
};

async function request(
  path: string,
  key: string,
  method = "GET",
  body?: unknown
) {
  const response = await fetch(path, {
    method,
    headers: {
      Authorization: "Bearer " + key,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "request_failed");
  return value;
}

export function App() {
  const [workspaceKey, setWorkspaceKey] = useState("");
  const [operatorKey, setOperatorKey] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [state, setState] = useState(initial);
  const [ready, setReady] = useState<boolean | null>(null);
  const [diagnostics, setDiagnostics] = useState(false);
  const [stage, setStage] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [level, setLevel] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [draft, setDraft] = useState({ transcript: "", reply: "" });
  const [tool, setTool] = useState("");
  const [review, setReview] = useState(false);
  const [sessions, setSessions] = useState<Array<Record<string, any>>>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [fault, setFault] = useState("none");
  const socket = useRef<WebSocket | null>(null);
  const context = useRef<AudioContext | null>(null);
  const capture = useRef(new Capture());
  const playback = useRef<Playback | null>(null);
  const epoch = useRef(0);

  function send(control: Control) {
    if (socket.current?.readyState === WebSocket.OPEN)
      socket.current.send(JSON.stringify(control));
  }
  function stopMedia() {
    capture.current.stop();
    playback.current?.invalidate();
    setLevel(0);
  }
  async function refresh() {
    const current = sessionRef.current;
    if (current) {
      try {
        setDetail(await request("/api/sessions/" + current.id, current.token));
      } catch (error) {
        setMessage((error as Error).message);
      }
    }
  }
  useEffect(() => {
    let alive = true;
    async function health() {
      try {
        const response = await fetch("/health");
        if (alive) setReady(response.ok);
      } catch {
        if (alive) setReady(false);
      }
    }
    health();
    fetch("/api/config")
      .then((r) => r.json())
      .then((v) => {
        if (alive) setDiagnostics(v.diagnostics);
      })
      .catch(() => {});
    const interval = setInterval(health, 10000);
    return () => {
      alive = false;
      clearInterval(interval);
      capture.current.stop();
      playback.current?.invalidate();
      socket.current?.close();
      context.current?.close();
    };
  }, []);

  function connect(current: Session) {
    stopMedia();
    setDraft({ transcript: "", reply: "" });
    socket.current?.close();
    setState(initial);
    setStage("");
    setMessage("");
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      protocol + "//" + location.host + "/api/sessions/" + current.id + "/audio"
    );
    socket.current = ws;
    ws.onopen = () =>
      ws.send(JSON.stringify({ type: "authenticate", token: current.token }));
    ws.onmessage = ({ data }) => {
      if (socket.current !== ws) return;
      try {
        const event = JSON.parse(data);
        if (event.type === "state") {
          setState(event);
          epoch.current = event.epoch;
          if (!event.recording) capture.current.stop();
          if (
            event.phase === "handoff_pending" ||
            event.phase === "operator" ||
            event.phase === "closed"
          )
            stopMedia();
          if (playback.current && playback.current.epoch < event.epoch)
            playback.current.reset(event.epoch);
          refresh();
        } else if (event.type === "stop_audio") {
          setDraft({ transcript: "", reply: "" });
          epoch.current = event.epoch;
          playback.current?.reset(event.epoch);
          send({ type: "playback_stopped", epoch: event.epoch });
        } else if (event.type === "audio") {
          playback.current?.enqueue(event);
        } else if (event.type === "speech") {
          setDraft({ transcript: "", reply: "" });
          setStage("");
          setMessage("");
        } else if (event.type === "stage") setStage(event.stage);
        else if (event.type === "transcript")
          setDraft((value) => ({ ...value, transcript: event.text }));
        else if (event.type === "reply")
          setDraft((value) => ({ ...value, reply: event.text }));
        else if (event.type === "completed") {
          setDraft({ transcript: "", reply: "" });
          setStage("done");
          refresh();
        } else if (event.type === "tool") {
          setTool(
            event.state === "completed"
              ? `${event.service}: ${
                  event.result.status
                } · receipt ${event.id.slice(0, 8)}`
              : `Lookup ${event.state}`
          );
          refresh();
        } else if (event.type === "error") {
          setDraft({ transcript: "", reply: "" });
          setMessage(event.code);
          refresh();
        }
      } catch {
        stopMedia();
        setMessage("Audio delivery was interrupted. Reconnect to continue.");
        ws.close();
      }
    };
    ws.onclose = () => {
      if (socket.current === ws) {
        stopMedia();
        setState((value) => ({ ...value, connected: false, recording: false }));
        setStage("");
        refresh();
      }
    };
    ws.onerror = () => {
      if (socket.current === ws)
        setMessage(
          "Connection unavailable. Check the local services, then reconnect."
        );
    };
  }
  async function createSession(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const current = await request("/api/sessions", workspaceKey, "POST");
      sessionRef.current = current;
      setSession(current);
      setDetail(null);
      setDraft({ transcript: "", reply: "" });
      connect(current);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    setBusy(true);
    setMessage("");
    try {
      if (!context.current) context.current = new AudioContext();
      await context.current.resume();
      if (!playback.current)
        playback.current = new Playback(context.current, send);
      playback.current.reset(epoch.current);
      await capture.current.start(
        context.current,
        (packet) => {
          const ws = socket.current;
          if (
            !ws ||
            ws.readyState !== WebSocket.OPEN ||
            ws.bufferedAmount > 32000
          ) {
            stopMedia();
            send({ type: "stop" });
            setMessage(
              "Upload is too slow. Recording stopped to keep audio bounded."
            );
            return;
          }
          ws.send(packet);
        },
        () => send({ type: "start" }),
        setLevel
      );
    } catch {
      stopMedia();
      setMessage(
        "Microphone access failed. Allow microphone access on localhost and try again."
      );
    } finally {
      setBusy(false);
    }
  }
  function action(type: string) {
    if (type === "interrupt") playback.current?.invalidate();
    else stopMedia();
    send({ type });
  }
  async function loadSessions() {
    try {
      setSessions(
        (await request("/api/operator/sessions", operatorKey)).sessions
      );
      setMessage("");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }
  async function select(identity: string) {
    try {
      setSelected(
        await request("/api/operator/sessions/" + identity, operatorKey)
      );
    } catch (error) {
      setMessage((error as Error).message);
    }
  }
  async function handoffAction(kind: string) {
    if (!selected) return;
    try {
      setSelected(
        await request(
          "/api/operator/sessions/" + selected.session.id + "/" + kind,
          operatorKey,
          "POST",
          kind === "accept" ? { epoch: selected.session.epoch } : undefined
        )
      );
      await loadSessions();
    } catch (error) {
      setMessage((error as Error).message);
    }
  }
  function exportDetail(value: Detail) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" })
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "voice-session-" + value.session.id + ".json";
    link.click();
    URL.revokeObjectURL(url);
  }
  const locked = ["handoff_pending", "operator", "closed"].includes(
    state.phase
  );
  const title =
    state.phase === "speaking"
      ? "A response is playing."
      : state.phase === "thinking"
      ? "Working on your turn."
      : state.recording
      ? "Listening to you."
      : state.phase === "handoff_pending"
      ? "An operator can take over."
      : state.phase === "operator"
      ? "The operator has the context."
      : "Ready when you are.";
  const last = detail?.turns.at(-1);
  return (
    <div className="shell">
      <header>
        <a
          className="brand"
          href="/"
          aria-label="Voice Reliability Workbench home"
        >
          <span className="mark" aria-hidden="true">
            v.
          </span>
          <span>
            Voice Reliability<span className="subbrand">WORKBENCH</span>
          </span>
        </a>
        <div className="header-right">
          <span className={"status " + (ready ? "up" : "")}>
            {ready === null
              ? "Checking services"
              : ready
              ? "Local services ready"
              : "Providers unavailable"}
          </span>
          <button className="text-button" onClick={() => setReview(!review)}>
            {review ? "Call workspace" : "Operator review"}{" "}
            <span aria-hidden="true">↗</span>
          </button>
        </div>
      </header>
      <main>
        <div className="intro">
          <p className="eyebrow">CONVERSATIONS, UNDER CONTROL</p>
          <h1>A voice you can inspect.</h1>
          <p>
            Speak, interrupt, reconnect. Follow each turn from microphone to
            response, and bring an operator into the conversation.
          </p>
        </div>
        {message && (
          <div className="notice" role="alert">
            {message.replace(/_/g, " ")}
            <button aria-label="Dismiss message" onClick={() => setMessage("")}>
              ×
            </button>
          </div>
        )}
        {!review ? (
          <div className="workspace">
            <section className="call-panel" aria-labelledby="call-title">
              <div className="panel-heading">
                <span className="eyebrow">01 / CALL WORKSPACE</span>
                <span className="session-id">
                  {session
                    ? "SESSION " + session.id.slice(0, 8)
                    : "NO ACTIVE SESSION"}
                </span>
              </div>
              <div
                className={"voice-orb " + (state.recording ? "active" : "")}
                aria-hidden="true"
              >
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
              <h2 id="call-title">{title}</h2>
              <p className="call-copy">
                {state.recording
                  ? "Your microphone is on. Pause after a sentence to finish a turn."
                  : locked
                  ? "Assistant recording is paused. Review the transcript in the operator workspace."
                  : "Microphone access begins only when you choose Start microphone."}
              </p>
              {!session ? (
                <form className="connect-form" onSubmit={createSession}>
                  <label htmlFor="workspace-key">Workspace key</label>
                  <input
                    id="workspace-key"
                    type="password"
                    autoComplete="off"
                    value={workspaceKey}
                    onChange={(e) => setWorkspaceKey(e.target.value)}
                    placeholder="Enter your local workspace key"
                  />
                  <button
                    className="primary"
                    disabled={busy || workspaceKey.length < 32}
                  >
                    {busy ? "Connecting…" : "Create a conversation"}
                  </button>
                </form>
              ) : (
                <>
                  <div className="call-controls">
                    <button
                      className="primary"
                      disabled={!state.connected || locked || busy}
                      onClick={() =>
                        state.recording ? action("stop") : start()
                      }
                    >
                      {state.recording
                        ? "Stop microphone"
                        : busy
                        ? "Opening microphone…"
                        : "Start microphone"}
                    </button>
                    <button
                      className="secondary"
                      disabled={!state.connected || locked}
                      onClick={() => action("interrupt")}
                    >
                      Interrupt response
                    </button>
                  </div>
                  <div className="level">
                    <label htmlFor="input-level">MICROPHONE LEVEL</label>
                    <meter id="input-level" min="0" max="0.3" value={level} />
                    <span>{state.recording ? "LIVE" : "OFF"}</span>
                  </div>
                  <div className="small-actions">
                    <button disabled={locked} onClick={() => connect(session)}>
                      Reconnect
                    </button>
                    <button
                      disabled={!state.connected || locked}
                      onClick={() => action("handoff")}
                    >
                      Request an operator
                    </button>
                  </div>
                </>
              )}
              <div className="call-footer">
                <span>Browser audio · local CPU</span>
                <span>
                  {state.connected ? "Connected" : "Disconnected"} / turn{" "}
                  {state.epoch}
                </span>
              </div>
            </section>
            <aside className="inspector" aria-label="Turn inspector">
              <div className="panel-heading">
                <span className="eyebrow">02 / TURN INSPECTOR</span>
                <span className="pill">{state.phase.replace(/_/g, " ")}</span>
              </div>
              <h2>Every step, visible.</h2>
              <ol className="stages">
                {stages.map((value, index) => (
                  <li
                    key={value}
                    className={stage.startsWith(value) ? "selected" : ""}
                  >
                    <span className="step">0{index + 1}</span>
                    <div>
                      <strong>{stageNames[value]}</strong>
                      <p>
                        {stage === value + "_start"
                          ? "Processing now"
                          : last?.timings[value + "_ms"]
                          ? `${Math.round(
                              last.timings[value + "_ms"]
                            )} ms on last completed turn`
                          : "Waiting for a turn"}
                      </p>
                    </div>
                    <span className="stage-indicator" />
                  </li>
                ))}
              </ol>
              <div className="latency">
                <span>First audio acknowledgement</span>
                <strong>
                  {last?.timings.first_audio_ms
                    ? `${(last.timings.first_audio_ms / 1000).toFixed(2)}s`
                    : "—"}
                </strong>
                <small>
                  From utterance end to the browser’s playback-start message.
                </small>
              </div>
              <div className="tool-box">
                <label htmlFor="service">Read-only demo lookup</label>
                <div className="inline">
                  <select id="service" defaultValue="atlas">
                    <option value="atlas">Atlas service</option>
                    <option value="beacon">Beacon service</option>
                  </select>
                  <button
                    disabled={!state.connected || locked}
                    onClick={() =>
                      send({
                        type: "tool",
                        service: (
                          document.getElementById(
                            "service"
                          ) as HTMLSelectElement
                        ).value,
                      })
                    }
                  >
                    Look up
                  </button>
                </div>
                <p role="status">
                  {tool ||
                    "Explicit lookup with a deadline and a single-use result receipt."}
                </p>
              </div>
              {diagnostics && (
                <details className="diagnostics">
                  <summary>Reliability scenarios</summary>
                  <label htmlFor="fault">Delay the next provider stage</label>
                  <select
                    id="fault"
                    value={fault}
                    disabled={!state.connected}
                    onChange={(e) => {
                      setFault(e.target.value);
                      send({ type: "fault", stage: e.target.value });
                    }}
                  >
                    <option value="none">Normal operation</option>
                    <option value="stt">Speech recognition timeout</option>
                    <option value="model">Model response timeout</option>
                    <option value="tts">Speech synthesis timeout</option>
                    <option value="tool">Tool lookup timeout</option>
                  </select>
                  <p>
                    Uses the real provider path with an injected delay and a
                    shorter deadline.
                  </p>
                </details>
              )}
            </aside>
            <section className="transcript-panel">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">03 / CONVERSATION RECORD</span>
                  <h2>What was said.</h2>
                </div>
                {detail && (
                  <button
                    className="text-button"
                    onClick={() => exportDetail(detail)}
                  >
                    Export trace ↓
                  </button>
                )}
              </div>
              <Transcript turns={detail?.turns || []} draft={draft} />
            </section>
          </div>
        ) : (
          <section className="review-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">OPERATOR WORKSPACE</span>
                <h2>Context before takeover.</h2>
              </div>
            </div>
            <form
              className="operator-form"
              onSubmit={(e) => {
                e.preventDefault();
                loadSessions();
              }}
            >
              <label htmlFor="operator-key">Operator key</label>
              <input
                id="operator-key"
                type="password"
                value={operatorKey}
                onChange={(e) => setOperatorKey(e.target.value)}
                autoComplete="off"
              />
              <button className="primary" disabled={operatorKey.length < 32}>
                Load conversations
              </button>
            </form>
            <div className="review-grid">
              <nav aria-label="Conversations">
                {sessions.length === 0 ? (
                  <p className="muted">
                    Enter the operator key to load session history.
                  </p>
                ) : (
                  sessions.map((row) => (
                    <button
                      className={
                        "session-row " +
                        (selected?.session.id === row.id ? "chosen" : "")
                      }
                      key={row.id}
                      onClick={() => select(row.id)}
                    >
                      <strong>{row.id.slice(0, 8)}</strong>
                      <span>{row.phase.replace(/_/g, " ")}</span>
                    </button>
                  ))
                )}
              </nav>
              <div>
                {selected ? (
                  <>
                    <div className="review-actions">
                      <span className="pill">
                        {selected.session.phase.replace(/_/g, " ")}
                      </span>
                      <button
                        disabled={selected.session.phase !== "handoff_pending"}
                        onClick={() => handoffAction("accept")}
                      >
                        Accept handoff
                      </button>
                      <button
                        disabled={selected.session.phase !== "operator"}
                        onClick={() => handoffAction("complete")}
                      >
                        Complete conversation
                      </button>
                      <button onClick={() => exportDetail(selected)}>
                        Export trace
                      </button>
                    </div>
                    <Transcript turns={selected.turns} />
                    <details className="timeline">
                      <summary>
                        Inspect event timeline ({selected.events.length})
                      </summary>
                      <ol>
                        {selected.events.map((event) => (
                          <li key={event.id}>
                            <span>Turn {event.epoch}</span>
                            <strong>{event.kind.replace(/_/g, " ")}</strong>
                            <code>{JSON.stringify(event.detail)}</code>
                          </li>
                        ))}
                      </ol>
                    </details>
                  </>
                ) : (
                  <p className="empty">
                    Choose a conversation to review the transcript, stage timing
                    and handoff state.
                  </p>
                )}
              </div>
            </div>
          </section>
        )}
        <footer>
          <span>Voice Reliability Workbench</span>
          <span>
            Local demonstration · synthetic fixture measurements · no carrier
            connection
          </span>
        </footer>
      </main>
    </div>
  );
}

function Transcript({
  turns,
  draft,
}: {
  turns: Turn[];
  draft?: { transcript: string; reply: string };
}) {
  const pending = Boolean(draft?.transcript || draft?.reply);
  return (
    <div className="transcript" aria-live="polite">
      {turns.length === 0 && !pending ? (
        <div className="empty">
          <span className="empty-symbol" aria-hidden="true">
            “
          </span>
          <p>Your conversation will appear here.</p>
          <small>
            Recognition and model responses are shown as produced. You can
            interrupt at any time.
          </small>
        </div>
      ) : (
        <>
          {turns
            .filter((turn) => turn.state !== "running")
            .map((turn) => (
              <article className="turn" key={turn.epoch}>
                <div className="turn-heading">
                  <span>TURN {turn.epoch}</span>
                  <span
                    className={
                      "pill " + (turn.state === "failed" ? "failed" : "")
                    }
                  >
                    {turn.state}
                  </span>
                </div>
                {turn.transcript && (
                  <p>
                    <span className="speaker">YOU</span>
                    {turn.transcript}
                  </p>
                )}
                {turn.reply && (
                  <p>
                    <span className="speaker assistant">ASSISTANT</span>
                    {turn.reply}
                  </p>
                )}
                {turn.error_code && (
                  <small>{turn.error_code.replace(/_/g, " ")}</small>
                )}
              </article>
            ))}
          {pending && (
            <article className="turn pending">
              <div className="turn-heading">
                <span>CURRENT TURN</span>
                <span className="pill">In progress</span>
              </div>
              {draft?.transcript && (
                <p>
                  <span className="speaker">YOU</span>
                  {draft.transcript}
                </p>
              )}
              {draft?.reply && (
                <p>
                  <span className="speaker assistant">ASSISTANT</span>
                  {draft.reply}
                </p>
              )}
            </article>
          )}
        </>
      )}
    </div>
  );
}
