// Live store for the tuning readout strip: one row per sounding voice plus the
// shared drift. Fed by the voice engine's 20 ms tick; notifications coalesce to
// one animation frame.

import { useEffect, useReducer } from "react";
import type { Role } from "../state/config";
import type { Approach, Breakdown } from "./engine";

export interface ReadoutRow {
  voiceKey: string;
  petal: number;
  key: number;
  note: number;
  role: Role;
  approach: Approach;
  breakdown: Breakdown;
}

const rows = new Map<string, ReadoutRow>();
let driftCents = 0;
const listeners = new Set<() => void>();

let frame = 0;
function notify() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    for (const l of listeners) l();
  });
}

export function setReadoutRow(row: ReadoutRow) {
  rows.set(row.voiceKey, row);
  notify();
}

export function removeReadoutRow(voiceKey: string) {
  rows.delete(voiceKey);
  notify();
}

export function setDrift(c: number) {
  driftCents = c;
  notify();
}

export function getReadoutRows(): ReadoutRow[] {
  return [...rows.values()];
}

export function getDrift(): number {
  return driftCents;
}

export function useReadoutTick(): number {
  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    listeners.add(bump);
    return () => {
      listeners.delete(bump);
    };
  }, []);
  return tick;
}
