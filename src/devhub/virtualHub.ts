// Virtual hub (handoff 5.1): fakes the real hub so the app can be developed
// without hardware. It emits BYTE-IDENTICAL MIDI to the real hub — same note
// table, same per-petal channels, CC11 sent before each Note On — so the voice
// engine can't tell them apart.
//
// On key down: send the petal's CC11 (starting at 60, ramping to 127 over ~1 s
// while held), then Note On with velocity 110. On key up: Note Off.

import { hubChannelFor, noteFor } from "../midi/hubTable";

type Sink = (bytes: number[]) => void;

const START_PRESSURE = 60;
const RAMP_MS = 1000;
const TICK_MS = 50;
const VELOCITY = 110;

export class VirtualHub {
  private sink: Sink;
  private keysDown = new Map<number, Set<number>>(); // petal -> keys held
  private pressure = new Map<number, number>(); // petal -> current CC11
  private rampTimer: ReturnType<typeof setInterval> | undefined;

  constructor(sink: Sink) {
    this.sink = sink;
  }

  private petalKeys(petal: number): Set<number> {
    let s = this.keysDown.get(petal);
    if (!s) {
      s = new Set();
      this.keysDown.set(petal, s);
    }
    return s;
  }

  keyDown(petal: number, k: number) {
    const held = this.petalKeys(petal);
    if (held.has(k)) return; // ignore auto-repeat
    const first = held.size === 0;
    held.add(k);
    if (first) {
      this.pressure.set(petal, START_PRESSURE);
      this.ensureRamp();
    }
    const ch = hubChannelFor(petal);
    const p = Math.round(this.pressure.get(petal) ?? START_PRESSURE);
    this.sink([0xb0 | (ch - 1), 11, p]); // CC11 before Note On, like the hub
    this.sink([0x90 | (ch - 1), noteFor(petal, k), VELOCITY]);
  }

  keyUp(petal: number, k: number) {
    const held = this.petalKeys(petal);
    if (!held.has(k)) return;
    held.delete(k);
    const ch = hubChannelFor(petal);
    this.sink([0x80 | (ch - 1), noteFor(petal, k), 0]);
    if (held.size === 0) this.pressure.set(petal, 0);
    this.maybeStopRamp();
  }

  allUp() {
    for (const [petal, held] of this.keysDown) {
      for (const k of [...held]) this.keyUp(petal, k);
    }
  }

  private ensureRamp() {
    if (this.rampTimer != null) return;
    const step = (127 - START_PRESSURE) * (TICK_MS / RAMP_MS);
    this.rampTimer = setInterval(() => {
      let anyHeld = false;
      for (const [petal, held] of this.keysDown) {
        if (held.size === 0) continue;
        anyHeld = true;
        const cur = this.pressure.get(petal) ?? START_PRESSURE;
        const next = Math.min(127, cur + step);
        if (Math.round(next) !== Math.round(cur)) {
          this.pressure.set(petal, next);
          const ch = hubChannelFor(petal);
          this.sink([0xb0 | (ch - 1), 11, Math.round(next)]);
        } else {
          this.pressure.set(petal, next);
        }
      }
      if (!anyHeld) this.maybeStopRamp();
    }, TICK_MS);
  }

  private maybeStopRamp() {
    const anyHeld = [...this.keysDown.values()].some((s) => s.size > 0);
    if (!anyHeld && this.rampTimer != null) {
      clearInterval(this.rampTimer);
      this.rampTimer = undefined;
    }
  }
}
