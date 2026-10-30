// Live, non-persisted instrument state: which keys are down, current pressure,
// and which petals are present. Updated at MIDI-event rate; notifications are
// coalesced to one animation frame so React re-renders at most ~60 Hz.

import { useEffect, useReducer } from "react";
import { KEYS_PER_PETAL } from "../midi/hubTable";

export interface PetalLive {
  keysDown: boolean[]; // length 6, index k
  pressure: number; // 0..127, per-petal (CC11) until poly aftertouch arrives
  lastActivity: number; // performance.now() of the last event
}

function blank(): PetalLive {
  return { keysDown: Array(KEYS_PER_PETAL).fill(false), pressure: 0, lastActivity: 0 };
}

const petals = new Map<number, PetalLive>();
const presentSet = new Set<number>(); // explicit presence (dev toggles / hub message)
const listeners = new Set<() => void>();

const PRESENCE_FALLBACK_MS = 10_000;

let frame = 0;
function notify() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    for (const l of listeners) l();
  });
}

export function subscribeLive(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function getLive(id: number): PetalLive {
  let p = petals.get(id);
  if (!p) {
    p = blank();
    petals.set(id, p);
  }
  return p;
}

export function setKeyDown(id: number, k: number, down: boolean) {
  const p = getLive(id);
  p.keysDown[k] = down;
  p.lastActivity = performance.now();
  notify();
}

export function setPressure(id: number, v: number) {
  const p = getLive(id);
  p.pressure = v;
  p.lastActivity = performance.now();
  notify();
}

export function clearPetalLive(id: number) {
  const p = getLive(id);
  p.keysDown.fill(false);
  p.pressure = 0;
  notify();
}

export function setPresent(id: number, present: boolean) {
  if (present) presentSet.add(id);
  else presentSet.delete(id);
  notify();
}

export function isPresent(id: number): boolean {
  if (presentSet.has(id)) return true;
  const p = petals.get(id);
  return !!p && performance.now() - p.lastActivity < PRESENCE_FALLBACK_MS;
}

/** Only the explicit presence flag (dev toggles / hub message), ignoring the
 *  activity fallback. Used by the dev panel toggles so their on/off is stable. */
export function isForcedPresent(id: number): boolean {
  return presentSet.has(id);
}

/** Re-render on any live change (coalesced to one frame). Returns a changing tick. */
export function useLiveTick(): number {
  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => subscribeLive(bump), []);
  return tick;
}
