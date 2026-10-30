// Developer panel: the virtual-hub keyboard help, presence toggles, and a raw
// MIDI monitor. (Event-log CSV and more land in later steps.)

import { clearMonitor, getMonitor, useMonitorTick } from "../devhub/midiMonitor";
import {
  clearLog,
  downloadLogCSV,
  getLogCount,
  isLogEnabled,
  setLogEnabled,
  useLogTick,
} from "../devhub/eventLog";
import { isForcedPresent, setPresent, useLiveTick } from "../state/liveState";

const KEYBOARD_ROWS = [
  { petal: 1, keys: "1 2 3 4 5 6" },
  { petal: 2, keys: "Q W E R T Y" },
  { petal: 3, keys: "A S D F G H" },
];

export function DevPanel() {
  useLiveTick();
  useMonitorTick();
  useLogTick();
  const monitor = getMonitor();
  const logCount = getLogCount();
  const recent = monitor.slice(-40).reverse();

  return (
    <section className="panel dev">
      <h2>Developer · Virtual hub</h2>
      <p className="hint">
        Your computer keyboard plays petal keys (C D E F G A around the hexagon).
        Hold <kbd>Shift</kbd> for petals 4–6. <kbd>Esc</kbd> = panic (all notes off).
      </p>

      <div className="kbd-help">
        {KEYBOARD_ROWS.map((row) => (
          <div key={row.petal} className="kbd-row">
            <span className="pill">Petal {row.petal}</span>
            <code>{row.keys}</code>
            <span className="muted">Shift → petal {row.petal + 3}</span>
          </div>
        ))}
      </div>

      <div className="presence-toggles">
        <span className="muted">Mark present:</span>
        {[1, 2, 3, 4, 5, 6].map((id) => (
          <button
            key={id}
            type="button"
            className={`toggle${isForcedPresent(id) ? " on" : ""}`}
            onClick={() => setPresent(id, !isForcedPresent(id))}
          >
            {id}
          </button>
        ))}
      </div>

      <div className="monitor-head">
        <span>MIDI monitor</span>
        <button type="button" className="link" onClick={clearMonitor}>
          clear
        </button>
      </div>
      <div className="monitor">
        {recent.length === 0 && <div className="muted">Press keys to see MIDI…</div>}
        {recent.map((e, i) => (
          <div key={monitor.length - i} className="mon-row">
            {e.text}
          </div>
        ))}
      </div>

      <div className="log-section">
        <label className="check">
          <input
            type="checkbox"
            checked={isLogEnabled()}
            onChange={(e) => setLogEnabled(e.target.checked)}
          />
          Record event log
        </label>
        <span className="muted">{logCount} note{logCount === 1 ? "" : "s"}</span>
        <button className="chip" onClick={downloadLogCSV} disabled={logCount === 0}>
          Download CSV
        </button>
        <button className="link" onClick={clearLog} disabled={logCount === 0}>
          clear
        </button>
      </div>
    </section>
  );
}
