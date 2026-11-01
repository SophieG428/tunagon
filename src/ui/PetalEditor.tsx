// Petal editor (handoff 5.1): name, instrument, scale-fill, per-key notes,
// expression, volume/pan, tuning role, and test keys. Opens for one petal.

import { useEffect, useMemo, useState } from "react";
import {
  type RoleOverride,
  defaultExpressionMode,
  defaultPetalConfig,
} from "../state/config";
import { configStore, useConfig } from "../state/store";
import {
  EXTRA_PRESETS,
  FAVORITE_PRESETS,
  GM_FAMILIES,
  GM_NAMES,
  type InstrumentPreset,
} from "../midi/gmInstruments";
import { PITCH_CLASSES, SCALES, fillScale } from "../midi/scales";
import { computeRoles } from "../tuning/roles";
import { isPresent, useLiveTick } from "../state/liveState";
import { noteName } from "../util/notes";
import { Hexagon } from "./Hexagon";

const KEY_LETTERS = ["C", "D", "E", "F", "G", "A"]; // physical key labels k=0..5
const ROLE_OPTIONS: RoleOverride[] = ["auto", "top", "inner", "bass", "solo"];

interface Props {
  petalId: number;
  onClose: () => void;
  onTestKey: (petal: number, key: number) => void;
  onPetalChanged: (petal: number) => void; // release sounding voices after edits
}

export function PetalEditor({ petalId, onClose, onTestKey, onPetalChanged }: Props) {
  const config = useConfig();
  useLiveTick(); // role display reacts to presence
  const cfg = config.petals[petalId] ?? defaultPetalConfig(petalId);

  const [selectedKey, setSelectedKey] = useState(0);
  const [search, setSearch] = useState("");
  const [rootPc, setRootPc] = useState(0);
  const [octave, setOctave] = useState(4);
  const [scaleId, setScaleId] = useState(SCALES[0].id);

  const presentIds = [1, 2, 3, 4, 5, 6].filter(isPresent);
  const role = computeRoles(config, presentIds).get(petalId);
  // What "Auto" would resolve to for this petal (ignoring its own override).
  const autoRole = computeRoles(
    { ...config, petals: { ...config.petals, [petalId]: { ...cfg, roleOverride: "auto" } } },
    presentIds,
  ).get(petalId);

  // Keyboard: Escape closes; arrows nudge the selected key.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      const tag = (document.activeElement?.tagName ?? "").toUpperCase();
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const cur = cfg.keys[selectedKey];
      if (cur == null) return;
      let delta = 0;
      if (e.key === "ArrowUp" || e.key === "ArrowRight") delta = 1;
      else if (e.key === "ArrowDown" || e.key === "ArrowLeft") delta = -1;
      else return;
      e.preventDefault();
      if (e.shiftKey) delta *= 12;
      setKey(selectedKey, Math.max(0, Math.min(127, cur + delta)));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, cfg]);

  function setKey(k: number, note: number | null) {
    const keys = [...cfg.keys];
    keys[k] = note;
    configStore.updatePetal(petalId, { keys });
    onPetalChanged(petalId);
  }

  function pickInstrument(preset: InstrumentPreset) {
    configStore.updatePetal(petalId, {
      instrument: { bank: preset.bank, program: preset.program, name: preset.name },
      expressionMode: defaultExpressionMode(preset.program),
    });
    onPetalChanged(petalId);
  }

  // A favorite/list button is "on" only when both bank and program match.
  const isCurrent = (pr: InstrumentPreset) =>
    cfg.instrument.program === pr.program && (cfg.instrument.bank ?? 0) === pr.bank;

  function doFill() {
    const scale = SCALES.find((s) => s.id === scaleId) ?? SCALES[0];
    configStore.updatePetal(petalId, { keys: fillScale(rootPc, octave, scale.intervals) });
    onPetalChanged(petalId);
  }

  const filteredFamilies = useMemo(() => {
    const q = search.trim().toLowerCase();
    return GM_FAMILIES.map((fam) => {
      const programs = [];
      for (let p = fam.start; p < fam.start + 8; p++) {
        if (!q || GM_NAMES[p].toLowerCase().includes(q)) programs.push(p);
      }
      return { fam, programs };
    }).filter((g) => g.programs.length > 0);
  }, [search]);

  // Non-GM extras (Ukulele, Flugelhorn) surfaced in the search list too.
  const filteredExtras = useMemo(() => {
    const q = search.trim().toLowerCase();
    return EXTRA_PRESETS.filter((pr) => !q || pr.name.toLowerCase().includes(q));
  }, [search]);

  const cur = cfg.keys[selectedKey];
  const curPc = cur == null ? 0 : ((cur % 12) + 12) % 12;
  const curOct = cur == null ? 4 : Math.floor(cur / 12) - 1;

  function setSelectedNote(pc: number, oct: number) {
    setKey(selectedKey, Math.max(0, Math.min(127, (oct + 1) * 12 + pc)));
  }

  return (
    <div className="editor-overlay" onClick={onClose}>
      <div className="editor" onClick={(e) => e.stopPropagation()}>
        <div className="editor-head">
          <input
            className="name-input"
            value={cfg.name}
            onChange={(e) => configStore.updatePetal(petalId, { name: e.target.value })}
          />
          <button className="link" onClick={onClose}>
            Close
          </button>
        </div>

        {/* Instrument */}
        <section className="ed-block">
          <h3>Instrument</h3>
          <div className="now">{cfg.instrument.name}</div>
          <div className="favorites">
            {FAVORITE_PRESETS.map((pr) => (
              <button
                key={`${pr.bank}:${pr.program}`}
                className={`chip${isCurrent(pr) ? " on" : ""}`}
                onClick={() => pickInstrument(pr)}
              >
                {pr.name}
              </button>
            ))}
          </div>
          <input
            className="search"
            placeholder="Search 128 instruments…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="instrument-list">
            {filteredExtras.length > 0 && (
              <div className="family">
                <div className="family-name">More (GeneralUser GS)</div>
                {filteredExtras.map((pr) => (
                  <button
                    key={`${pr.bank}:${pr.program}`}
                    className={`inst${isCurrent(pr) ? " on" : ""}`}
                    onClick={() => pickInstrument(pr)}
                  >
                    {pr.name}
                  </button>
                ))}
              </div>
            )}
            {filteredFamilies.map(({ fam, programs }) => (
              <div key={fam.name} className="family">
                <div className="family-name">{fam.name}</div>
                {programs.map((p) => (
                  <button
                    key={p}
                    className={`inst${(cfg.instrument.bank ?? 0) === 0 && cfg.instrument.program === p ? " on" : ""}`}
                    onClick={() => pickInstrument({ bank: 0, program: p, name: GM_NAMES[p] })}
                  >
                    {GM_NAMES[p]}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </section>

        {/* Scale fill */}
        <section className="ed-block">
          <h3>Scale preset</h3>
          <div className="row">
            <label>
              Root
              <select value={rootPc} onChange={(e) => setRootPc(Number(e.target.value))}>
                {PITCH_CLASSES.map((n, i) => (
                  <option key={i} value={i}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Octave
              <select value={octave} onChange={(e) => setOctave(Number(e.target.value))}>
                {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Scale
              <select value={scaleId} onChange={(e) => setScaleId(e.target.value)}>
                {SCALES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" onClick={doFill}>
              Fill keys
            </button>
          </div>
        </section>

        {/* Per-key editor */}
        <section className="ed-block">
          <h3>Keys</h3>
          <div className="key-editor">
            <Hexagon cfg={cfg} size={190} onKeyClick={setSelectedKey} selectedKey={selectedKey} />
            <div className="key-picker">
              <div className="muted">
                Editing key {KEY_LETTERS[selectedKey]} (k={selectedKey})
              </div>
              <div className="row">
                <label>
                  Note
                  <select
                    value={curPc}
                    disabled={cur == null}
                    onChange={(e) => setSelectedNote(Number(e.target.value), curOct)}
                  >
                    {PITCH_CLASSES.map((n, i) => (
                      <option key={i} value={i}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Octave
                  <select
                    value={curOct}
                    disabled={cur == null}
                    onChange={(e) => setSelectedNote(curPc, Number(e.target.value))}
                  >
                    {[-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="row">
                <span className="midi-num">
                  {cur == null ? "silent" : `${noteName(cur)} · MIDI ${cur}`}
                </span>
              </div>
              <label className="check">
                <input
                  type="checkbox"
                  checked={cur == null}
                  onChange={(e) => setKey(selectedKey, e.target.checked ? null : (curOct + 1) * 12 + curPc)}
                />
                Silent key
              </label>
              <div className="muted small">
                Tip: click a triangle to select it, then use ↑/↓ (±1 semitone) or Shift+↑/↓ (±octave).
              </div>
            </div>
          </div>
        </section>

        {/* Expression + volume/pan */}
        <section className="ed-block">
          <h3>Expression</h3>
          <div className="row">
            <div className="segmented">
              {(["swell", "fixed"] as const).map((m) => (
                <button
                  key={m}
                  className={cfg.expressionMode === m ? "on" : ""}
                  onClick={() => configStore.updatePetal(petalId, { expressionMode: m })}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
          <label className="slider">
            Volume {Math.round(cfg.volume * 100)}%
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={cfg.volume}
              onChange={(e) => configStore.updatePetal(petalId, { volume: Number(e.target.value) })}
            />
          </label>
          <label className="slider">
            Pan {cfg.pan === 0 ? "C" : cfg.pan < 0 ? `L${Math.round(-cfg.pan * 100)}` : `R${Math.round(cfg.pan * 100)}`}
            <input
              type="range"
              min={-1}
              max={1}
              step={0.01}
              value={cfg.pan}
              onChange={(e) => configStore.updatePetal(petalId, { pan: Number(e.target.value) })}
            />
          </label>
        </section>

        {/* Tuning role */}
        <section className="ed-block">
          <h3>Tuning role</h3>
          <p className="muted">
            Which voice this petal plays in the Ensemble tuning (top is tuned sharp,
            inner flat, bass/solo neutral). <b>Auto</b> picks it from the petal's pitch —
            highest&nbsp;=&nbsp;top, lowest&nbsp;=&nbsp;bass. Tap one to force it.
          </p>
          <div className="role-picker">
            {ROLE_OPTIONS.map((r) => (
              <button
                key={r}
                type="button"
                className={`chip${cfg.roleOverride === r ? " on" : ""}`}
                onClick={() => configStore.updatePetal(petalId, { roleOverride: r })}
              >
                {r === "auto" ? `Auto${autoRole ? ` · ${autoRole}` : ""}` : r}
              </button>
            ))}
          </div>
          <div className="muted">
            Playing as: <b>{role ?? "—"}</b>
          </div>
        </section>

        {/* Test + layout */}
        <section className="ed-block">
          <h3>Test keys</h3>
          <div className="test-keys">
            {[0, 1, 2, 3, 4, 5].map((k) => (
              <button key={k} className="chip" onClick={() => onTestKey(petalId, k)}>
                {KEY_LETTERS[k]}
                {cfg.keys[k] != null ? ` · ${noteName(cfg.keys[k]!)}` : " · —"}
              </button>
            ))}
          </div>
          <button className="link disabled" disabled title="Added in a later step">
            Match my petal (layout wizard) — later
          </button>
        </section>
      </div>
    </div>
  );
}
