// Tuning readout strip (handoff 5.1): for every sounding note, the offset
// breakdown that makes the research visible. Also shows the shared drift and
// each present petal's role.

import { useState } from "react";
import { getDrift, getReadoutRows, useReadoutTick } from "../tuning/readout";
import { useConfig } from "../state/store";
import { computeRoles } from "../tuning/roles";
import { isPresent, useLiveTick } from "../state/liveState";
import { noteName } from "../util/notes";

function fmt(c: number): string {
  return (c >= 0 ? "+" : "") + c.toFixed(1);
}

export function TuningReadout() {
  useReadoutTick();
  useLiveTick();
  const config = useConfig();
  const [open, setOpen] = useState(true);

  const equal = config.tuning.mode === "equal";
  const rows = getReadoutRows().sort((a, b) => a.petal - b.petal || a.key - b.key);
  const presentIds = [1, 2, 3, 4, 5, 6].filter(isPresent);
  const roles = computeRoles(config, presentIds);

  return (
    <section className="panel readout">
      <button className="readout-head" onClick={() => setOpen((o) => !o)}>
        <h2>Tuning readout · {equal ? "equal temperament" : "ensemble (research)"}</h2>
        <span className="muted">
          drift {fmt(getDrift())} ¢ {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <>
          <div className="roles-row">
            {[1, 2, 3, 4, 5, 6].map((id) =>
              roles.get(id) ? (
                <span key={id} className="role-chip">
                  P{id} <b>{roles.get(id)}</b>
                </span>
              ) : null,
            )}
          </div>

          <div className="readout-rows">
            {rows.length === 0 && <div className="muted">Play a note to see its tuning…</div>}
            {rows.map((r) => (
              <div key={r.voiceKey} className="readout-row">
                <span className="rr-note">
                  P{r.petal} · {noteName(r.note)}
                </span>
                {equal ? (
                  <span className="muted">0.0 ¢ (equal temperament)</span>
                ) : (
                  <span className="rr-break">
                    <span className="term">role {fmt(r.breakdown.role)}</span>
                    {r.breakdown.step !== 0 && <span className="term">step {fmt(r.breakdown.step)}</span>}
                    {r.breakdown.leap !== 0 && <span className="term">leap {fmt(r.breakdown.leap)}</span>}
                    {r.breakdown.long !== 0 && <span className="term">long {fmt(r.breakdown.long)}</span>}
                    <span className="term">drift {fmt(r.breakdown.drift)}</span>
                    <span className="rr-total">= {fmt(r.breakdown.total)} ¢</span>
                  </span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
