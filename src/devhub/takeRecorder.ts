// Take recorder — captures the raw hub MIDI stream (real or virtual) as a "take"
// and replays it deterministically. Because the tuning model (Ensemble vs Equal
// Temperament) is applied only as pitch bend at playback time, replaying the SAME
// recorded key events under each mode produces two renders that line up
// note-for-note. Record your performance once, then replay it with Ensemble and
// with ET to get a perfectly-aligned A/B for a video.

import { useEffect, useState } from "react";

type Bytes = number[];
interface TakeEvent {
  t: number; // ms since the take started
  bytes: Bytes;
}

let events: TakeEvent[] = [];
let recording = false;
let recStart = 0;
let replaying = false;
let replayTimers: number[] = [];
let lastAudioBlob: Blob | null = null;
let lastAudioName = "";

const listeners = new Set<() => void>();
function emit() {
  for (const l of listeners) l();
}
function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

// --- Recording -------------------------------------------------------------

export function startRecording(): void {
  stopReplay();
  events = [];
  recStart = performance.now();
  recording = true;
  emit();
}

export function stopRecording(): void {
  if (!recording) return;
  recording = false;
  emit();
}

/** Called from the app's MIDI taps on every incoming message. Hot path: no emit. */
export function capture(bytes: number[] | Uint8Array): void {
  if (!recording) return;
  events.push({ t: performance.now() - recStart, bytes: Array.from(bytes) });
}

export function clearTake(): void {
  stopReplay();
  events = [];
  recording = false;
  emit();
}

export function isRecording(): boolean {
  return recording;
}
export function isReplaying(): boolean {
  return replaying;
}
export function eventCount(): number {
  return events.length;
}
export function hasTake(): boolean {
  return events.length > 0;
}
export function takeDurationMs(): number {
  return events.length ? events[events.length - 1].t : 0;
}

// --- Replay ----------------------------------------------------------------

interface ReplayOpts {
  onDone?: () => void;
  panic?: () => void;
}

/** Replay the take into `handleMidi`, firing each event at its recorded offset. */
export function replay(handleMidi: (bytes: number[]) => void, opts: ReplayOpts = {}): void {
  stopReplay(opts.panic);
  if (events.length === 0) {
    opts.onDone?.();
    return;
  }
  opts.panic?.();
  replaying = true;
  emit();
  for (const ev of events) {
    replayTimers.push(window.setTimeout(() => handleMidi(ev.bytes), ev.t));
  }
  // Finish a little after the last event so release tails ring out.
  const endAt = takeDurationMs() + 400;
  replayTimers.push(window.setTimeout(() => finishReplay(opts), endAt));
}

function finishReplay(opts: ReplayOpts): void {
  teardownReplay();
  emit(); // re-enable the Replay buttons once playback ends
  opts.onDone?.(); // stop + save the WAV before the panic silences the tail
  opts.panic?.();
}

export function stopReplay(panic?: () => void): void {
  if (!replaying && replayTimers.length === 0) return;
  teardownReplay();
  if (panic) panic();
  emit();
}

function teardownReplay(): void {
  for (const id of replayTimers) clearTimeout(id);
  replayTimers = [];
  replaying = false;
}

// --- Rendered audio (captured live while recording, or during a replay) -----

/** Store the most recently rendered WAV so it can be saved without replaying. */
export function setLastAudio(blob: Blob | null, label: string): void {
  lastAudioBlob = blob;
  lastAudioName = blob ? `tuneagon-${label}-${stamp()}.wav` : "";
  emit();
}
export function hasLastAudio(): boolean {
  return lastAudioBlob != null;
}
/** Download the stored WAV — no replay needed. */
export function saveLastAudio(): void {
  if (lastAudioBlob) download(lastAudioBlob, lastAudioName);
}

// --- Save / load a take ----------------------------------------------------

export function exportTake(): void {
  const blob = new Blob([JSON.stringify({ version: 1, events })], { type: "application/json" });
  download(blob, `tuneagon-take-${stamp()}.json`);
}

export async function importTake(file: File): Promise<void> {
  try {
    const data = JSON.parse(await file.text());
    if (Array.isArray(data?.events)) {
      events = data.events;
      emit();
    }
  } catch {
    // ignore a malformed file
  }
}

// --- helpers ---------------------------------------------------------------

/** Trigger a browser download of a blob. Exported for the WAV render in App. */
export function downloadBlob(blob: Blob, name: string): void {
  download(blob, name);
}

function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

/** Re-render the subscribing component whenever take state changes. */
export function useTakeTick(): void {
  const [, setN] = useState(0);
  useEffect(() => subscribe(() => setN((n) => n + 1)), []);
}
