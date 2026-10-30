// The main petal grid: slots for petals 1..6, each showing name, presence,
// instrument, and the live hexagon. Clicking a slot opens its editor.

import type { AppConfig } from "../state/config";
import { isPresent, useLiveTick } from "../state/liveState";
import { Hexagon } from "./Hexagon";

const PETAL_IDS = [1, 2, 3, 4, 5, 6];

export function PetalGrid({
  config,
  onSelect,
}: {
  config: AppConfig;
  onSelect: (id: number) => void;
}) {
  useLiveTick(); // re-render on key-down / pressure / presence changes

  return (
    <div className="petal-grid">
      {PETAL_IDS.map((id) => {
        const cfg = config.petals[id];
        const present = isPresent(id);
        return (
          <button key={id} type="button" className="petal-slot" onClick={() => onSelect(id)}>
            <div className="petal-head">
              <span className={`presence${present ? " on" : ""}`} title={present ? "present" : "not present"} />
              <span className="petal-name">{cfg.name}</span>
            </div>
            <div className="petal-instrument">{cfg.instrument.name}</div>
            <Hexagon cfg={cfg} />
          </button>
        );
      })}
    </div>
  );
}
