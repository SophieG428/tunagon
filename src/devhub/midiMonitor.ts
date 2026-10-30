// Raw MIDI monitor for the developer panel: a ring buffer of the last N messages
// (from the virtual hub now, the real hub later). Notifications coalesce to one
// animation frame so the CC ramp doesn't flood React with renders.

import { useEffect, useReducer } from "react";

export interface MonitorEntry {
  t: number; // performance.now()
  bytes: number[];
  text: string; // decoded, e.g. "NoteOn ch2 n71 v110"
}

const MAX = 200;
const entries: MonitorEntry[] = [];
const listeners = new Set<() => void>();

let frame = 0;
function notify() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    for (const l of listeners) l();
  });
}

function decode(bytes: number[]): string {
  const status = bytes[0];
  const cmd = status & 0xf0;
  const ch = (status & 0x0f) + 1;
  switch (cmd) {
    case 0x80:
      return `NoteOff ch${ch} n${bytes[1]}`;
    case 0x90:
      return bytes[2] > 0 ? `NoteOn  ch${ch} n${bytes[1]} v${bytes[2]}` : `NoteOff ch${ch} n${bytes[1]}`;
    case 0xa0:
      return `PolyAT  ch${ch} n${bytes[1]} ${bytes[2]}`;
    case 0xb0:
      return `CC      ch${ch} #${bytes[1]} ${bytes[2]}`;
    case 0xc0:
      return `Program ch${ch} ${bytes[1]}`;
    case 0xe0:
      return `Bend    ch${ch} ${(bytes[2] << 7) | bytes[1]}`;
    case 0xf0:
      return `SysEx   ${bytes.map((b) => b.toString(16).padStart(2, "0")).join(" ")}`;
    default:
      return bytes.map((b) => b.toString(16).padStart(2, "0")).join(" ");
  }
}

export function pushMidi(bytes: number[] | Uint8Array) {
  const arr = Array.from(bytes);
  entries.push({ t: performance.now(), bytes: arr, text: decode(arr) });
  if (entries.length > MAX) entries.splice(0, entries.length - MAX);
  notify();
}

export function getMonitor(): readonly MonitorEntry[] {
  return entries;
}

export function clearMonitor() {
  entries.length = 0;
  notify();
}

export function useMonitorTick(): number {
  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    listeners.add(bump);
    return () => {
      listeners.delete(bump);
    };
  }, []);
  return tick;
}
