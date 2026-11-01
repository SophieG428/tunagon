// Event log (handoff 7.6): one row per sounding note, captured at note-on and
// finalized at note-off, downloadable as CSV. This is the evidence for "here is
// what my instrument does" and the training data for the section-11 ML model.

import { useEffect, useReducer } from "react";

export interface LogRow {
  time_ms: number; // wall-clock (epoch ms) at note-on
  petal: number;
  key: number;
  note: number;
  velocity_hub: number;
  velocity_app: number;
  role: string;
  approach: string;
  role_cents: number;
  step_cents: number;
  long_cents_at_off: number;
  drift_cents: number;
  total_cents_at_on: number;
  total_cents_at_off: number;
  duration_ms: number;
  instrument: string;
}

const COLUMNS: (keyof LogRow)[] = [
  "time_ms",
  "petal",
  "key",
  "note",
  "velocity_hub",
  "velocity_app",
  "role",
  "approach",
  "role_cents",
  "step_cents",
  "long_cents_at_off",
  "drift_cents",
  "total_cents_at_on",
  "total_cents_at_off",
  "duration_ms",
  "instrument",
];

let enabled = false;
const rows: LogRow[] = [];
const listeners = new Set<() => void>();
function notify() {
  for (const l of listeners) l();
}

export function setLogEnabled(b: boolean) {
  enabled = b;
  notify();
}
export function isLogEnabled(): boolean {
  return enabled;
}
export function appendLogRow(row: LogRow) {
  rows.push(row);
  notify();
}
export function getLogCount(): number {
  return rows.length;
}
export function clearLog() {
  rows.length = 0;
  notify();
}

function csvCell(v: string | number): string {
  const s = typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : v;
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function downloadLogCSV() {
  const header = COLUMNS.join(",");
  const body = rows.map((r) => COLUMNS.map((c) => csvCell(r[c])).join(",")).join("\n");
  const csv = `${header}\n${body}\n`;
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `tuneagon-events-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function useLogTick(): number {
  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    listeners.add(bump);
    return () => {
      listeners.delete(bump);
    };
  }, []);
  return tick;
}
