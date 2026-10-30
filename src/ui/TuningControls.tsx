// Top-bar tuning controls (handoff 5.1): the ET / Ensemble switch and the
// `scale` slider — the demo control you flip while playing.

import { configStore, useConfig } from "../state/store";

export function TuningControls() {
  const t = useConfig().tuning;
  const setMode = (mode: "equal" | "ensemble") =>
    configStore.update({ tuning: { ...t, mode } });
  const setScale = (scale: number) => configStore.update({ tuning: { ...t, scale } });

  return (
    <section className="panel tuning-controls">
      <div className="segmented">
        <button className={t.mode === "equal" ? "on" : ""} onClick={() => setMode("equal")}>
          Equal temperament
        </button>
        <button className={t.mode === "ensemble" ? "on" : ""} onClick={() => setMode("ensemble")}>
          Ensemble (research)
        </button>
      </div>
      <label className="slider scale-slider">
        Exaggerate ×{t.scale.toFixed(1)}
        <input
          type="range"
          min={0.5}
          max={5}
          step={0.1}
          value={t.scale}
          onChange={(e) => setScale(Number(e.target.value))}
        />
      </label>
    </section>
  );
}
