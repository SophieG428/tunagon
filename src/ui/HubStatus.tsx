// Hub status + MIDI input picker for the top bar (handoff 5.1).

import { midiInput, useMidiInput } from "../midi/midiInput";

export function HubStatus() {
  const s = useMidiInput();

  let text: string;
  let dot: string;
  switch (s.statusKind) {
    case "connected":
      text = `Hub: connected (${s.connectedName})`;
      dot = "ok";
      break;
    case "no-device":
      text = "Hub: not found";
      dot = "bad";
      break;
    case "denied":
      text = "MIDI blocked — allow it in Chrome";
      dot = "warn";
      break;
    case "unsupported":
      text = "Web MIDI needs Chrome";
      dot = "warn";
      break;
    default:
      text = "Hub: connecting…";
      dot = "";
  }

  return (
    <div className="hub-status">
      <span className={`hub-dot ${dot}`} />
      <span className="hub-text">{text}</span>
      {s.inputs.length > 0 && (
        <select
          className="hub-select"
          value={s.selectedId ?? ""}
          onChange={(e) => midiInput.selectInput(e.target.value)}
        >
          <option value="" disabled>
            Choose input…
          </option>
          {s.inputs.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
