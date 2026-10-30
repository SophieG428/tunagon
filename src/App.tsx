import { useEffect, useRef, useState } from "react";
import "./App.css";
import { SoundEngine } from "./audio/soundEngine";
import { VoiceEngine } from "./engine/voiceEngine";
import { VirtualHub } from "./devhub/virtualHub";
import { pushMidi } from "./devhub/midiMonitor";
import { useConfig } from "./state/store";
import { setPresent } from "./state/liveState";
import { PetalGrid } from "./ui/PetalGrid";
import { PetalEditor } from "./ui/PetalEditor";
import { DevPanel } from "./ui/DevPanel";

type AudioState = "idle" | "loading" | "ready" | "error";

// Computer-keyboard mapping (handoff 5.1): code -> [row, keyIndex].
// Row 0 = petal 1, row 1 = petal 2, row 2 = petal 3; Shift adds 3 (petals 4–6).
const KEY_ROWS: Record<string, [number, number]> = {};
["Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "Digit6"].forEach((c, i) => (KEY_ROWS[c] = [0, i]));
["KeyQ", "KeyW", "KeyE", "KeyR", "KeyT", "KeyY"].forEach((c, i) => (KEY_ROWS[c] = [1, i]));
["KeyA", "KeyS", "KeyD", "KeyF", "KeyG", "KeyH"].forEach((c, i) => (KEY_ROWS[c] = [2, i]));

function isTypingTarget(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    (el as HTMLElement).isContentEditable
  );
}

export default function App() {
  const config = useConfig();
  const engineRef = useRef<SoundEngine | null>(null);
  const voiceRef = useRef<VoiceEngine | null>(null);
  const hubRef = useRef<VirtualHub | null>(null);

  const [state, setState] = useState<AudioState>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedPetal, setSelectedPetal] = useState<number | null>(null);

  function handleTestKey(petal: number, key: number) {
    const hub = hubRef.current;
    if (!hub) return;
    hub.keyDown(petal, key);
    setTimeout(() => hub.keyUp(petal, key), 300);
  }

  function handlePetalChanged(petal: number) {
    voiceRef.current?.releasePetal(petal);
  }

  async function startAudio() {
    if (state === "loading" || state === "ready") return;
    setState("loading");
    setError(null);
    setProgress(0);
    const engine = new SoundEngine();
    engineRef.current = engine;
    try {
      await engine.init((p) => setProgress(p.total ? p.loaded / p.total : 0));
      const voice = new VoiceEngine(engine);
      voiceRef.current = voice;
      hubRef.current = new VirtualHub((bytes) => {
        voice.handleMidi(bytes);
        pushMidi(bytes);
      });
      setState("ready");
    } catch (e) {
      console.error(e);
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }

  // Computer keyboard -> virtual hub, active once audio is ready.
  useEffect(() => {
    if (state !== "ready") return;

    // Remember which (petal, key) each physical key triggered, so key-up
    // releases the right note even if Shift changed in between.
    const active = new Map<string, [number, number]>();

    const onDown = (e: KeyboardEvent) => {
      if (e.repeat || isTypingTarget(document.activeElement)) return;
      if (e.code === "Escape") {
        hubRef.current?.allUp();
        voiceRef.current?.panic();
        return;
      }
      const row = KEY_ROWS[e.code];
      if (!row) return;
      e.preventDefault();
      const [rowIdx, k] = row;
      const petal = rowIdx + 1 + (e.shiftKey ? 3 : 0);
      active.set(e.code, [petal, k]);
      setPresent(petal, true);
      hubRef.current?.keyDown(petal, k);
    };

    const onUp = (e: KeyboardEvent) => {
      const pk = active.get(e.code);
      if (!pk) return;
      active.delete(e.code);
      hubRef.current?.keyUp(pk[0], pk[1]);
    };

    const onBlur = () => hubRef.current?.allUp();
    const onVisibility = () => {
      if (document.hidden) {
        hubRef.current?.allUp();
        voiceRef.current?.panic();
      }
    };

    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [state]);

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Tunagon</h1>
          <p className="tagline">Modular instrument control &amp; adaptive tuning</p>
        </div>
        <div className="audio-status">
          {state === "ready" ? (
            <span className="status-ready">
              <span className="dot" /> Audio ready
            </span>
          ) : state === "loading" ? (
            <span className="loading-label">Loading… {Math.round(progress * 100)}%</span>
          ) : (
            <button className="primary" onClick={startAudio}>
              Start audio
            </button>
          )}
        </div>
      </header>

      {state === "idle" && (
        <section className="panel">
          <p className="hint">
            Click <b>Start audio</b> to load the GeneralUser GS SoundFont
            (~31&nbsp;MB, once) and begin. Then use your computer keyboard to play.
          </p>
        </section>
      )}

      {state === "loading" && (
        <section className="panel">
          <div className="progress">
            <div className="progress-bar" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
        </section>
      )}

      {state === "error" && (
        <section className="panel error">
          <p>Could not start audio.</p>
          <code>{error}</code>
          <div>
            <button className="primary" onClick={startAudio}>
              Try again
            </button>
          </div>
        </section>
      )}

      {state === "ready" && (
        <>
          <PetalGrid config={config} onSelect={setSelectedPetal} />
          <DevPanel />
        </>
      )}

      {selectedPetal != null && (
        <PetalEditor
          petalId={selectedPetal}
          onClose={() => setSelectedPetal(null)}
          onTestKey={handleTestKey}
          onPetalChanged={handlePetalChanged}
        />
      )}

      <footer className="app-footer">
        <p>
          Phase&nbsp;1A · Check&nbsp;B — the virtual hub plays through the
          configured petals and the triangles light. Next: the petal editor
          (instruments, scales, per-key notes).
        </p>
      </footer>
    </div>
  );
}
