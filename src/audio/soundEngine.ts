// Tunagon sound engine — wraps spessasynth_lib's WorkletSynthesizer.
//
// Audio graph:  WorkletSynthesizer (output 0 = main stereo mix)
//                 -> [FX chain inserted here in a later step] -> masterGain -> destination
//
// The synth does NOT auto-connect to the destination (verified in the v4.4.1
// source), so we connect it explicitly through masterGain. That gives us one
// place to insert the Settings -> Audio FX chain (reverb / distortion / delay / ...)
// without touching note handling.
//
// API reference used (spessasynth_lib v4.4.1, read from the installed .d.ts):
//   new WorkletSynthesizer(context, config?)
//   await context.audioWorklet.addModule(workletUrl)   // before constructing
//   synth.connect(node) / synth.disconnect(node)
//   synth.soundBankManager.addSoundBank(arrayBuffer, id)
//   await synth.isReady
//   synth.noteOn(ch, note, vel)  synth.noteOff(ch, note)
//   synth.programChange(ch, program)
//   synth.pitchWheel(ch, value14bit)  synth.pitchWheelRange(ch, semitones)
//   synth.controllerChange(ch, cc, value)  synth.sendMessage([status, d1, d2])

import { WorkletSynthesizer } from "spessasynth_lib";
import workletUrl from "spessasynth_lib/dist/spessasynth_processor.min.js?url";

/** Pitch-bend range, in semitones, set on every channel. 8192 steps / 200 cents
 *  = 0.024 cents/step — finer than audible. Kept in ONE place (handoff 6.1). */
export const BEND_RANGE_SEMITONES = 2;

/** All 16 MIDI channels (0-based). */
export const ALL_CHANNELS: readonly number[] = Array.from({ length: 16 }, (_, i) => i);

/** Channel pool for per-note voice allocation (handoff 6.3): channels 1–9 and
 *  11–16 = 0-based 0–8 and 10–15. Channel 10 (index 9) is GM drums; never used. */
export const VOICE_CHANNELS: readonly number[] = ALL_CHANNELS.filter((c) => c !== 9);

/** Default path to the bundled SoundFont. Uses BASE_URL so it resolves correctly
 *  both in dev and under a GitHub Pages subpath. */
export function soundFontUrl(): string {
  return `${import.meta.env.BASE_URL}soundfonts/GeneralUser-GS.sf2`;
}

export interface LoadProgress {
  loaded: number;
  total: number;
}

/** Convert a pitch offset in cents to a 14-bit pitch-wheel value (handoff 6.3). */
export function centsToPitchWheel(cents: number): number {
  const v = 8192 + Math.round((cents / (100 * BEND_RANGE_SEMITONES)) * 8192);
  return Math.max(0, Math.min(16383, v));
}

/** Fetch the SoundFont, reporting byte progress for the ~31 MB load. */
async function fetchArrayBufferWithProgress(
  url: string,
  onProgress?: (p: LoadProgress) => void,
): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not load SoundFont (HTTP ${res.status}) from ${url}`);

  const total = Number(res.headers.get("Content-Length")) || 0;
  if (!res.body || !total) {
    // No streaming / length info: fall back to a plain read.
    const buf = await res.arrayBuffer();
    onProgress?.({ loaded: buf.byteLength, total: buf.byteLength });
    return buf;
  }

  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress?.({ loaded, total });
  }
  const out = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out.buffer;
}

export class SoundEngine {
  context: AudioContext | null = null;
  synth: WorkletSynthesizer | null = null;
  masterGain: GainNode | null = null;
  ready = false;

  /** True once audio is running and the SoundFont is loaded. */
  get running(): boolean {
    return this.ready && this.context?.state === "running";
  }

  /**
   * Must be called from a user gesture (e.g. a button click) — browsers block
   * AudioContext start otherwise. Safe to call once; repeated calls are ignored.
   */
  async init(
    onProgress?: (p: LoadProgress) => void,
    masterVolume = 0.8,
  ): Promise<void> {
    if (this.context) return;

    const context = new AudioContext({ latencyHint: "interactive" });
    this.context = context;
    await context.resume();

    // Register the worklet processor, then construct the synth.
    await context.audioWorklet.addModule(workletUrl);
    const synth = new WorkletSynthesizer(context);
    this.synth = synth;

    // synth -> masterGain -> destination (FX chain slots in before masterGain later).
    const masterGain = context.createGain();
    masterGain.gain.value = masterVolume;
    masterGain.connect(context.destination);
    synth.connect(masterGain);
    this.masterGain = masterGain;

    // Load and register the SoundFont.
    const sfBuffer = await fetchArrayBufferWithProgress(soundFontUrl(), onProgress);
    await synth.soundBankManager.addSoundBank(sfBuffer, "main");
    await synth.isReady;

    this.configureChannels();
    this.ready = true;
  }

  /** Set a sane, dry starting state on every channel. */
  private configureChannels(): void {
    const synth = this.synth;
    if (!synth) return;
    for (const ch of ALL_CHANNELS) {
      // Dry by default (Sophie's choice): effects live in a Settings -> Audio FX
      // panel added in a later step. Zero the reverb (CC91) and chorus (CC93) sends.
      synth.sendMessage([0xb0 | ch, 91, 0]);
      synth.sendMessage([0xb0 | ch, 93, 0]);
      // Pitch-bend range ±BEND_RANGE_SEMITONES for the tuning engine.
      synth.pitchWheelRange(ch, BEND_RANGE_SEMITONES);
    }
  }

  setMasterVolume(v: number): void {
    if (this.masterGain) this.masterGain.gain.value = Math.max(0, Math.min(1, v));
  }

  // --- Low-level MIDI, used by the full engine in later steps ---

  noteOn(channel: number, note: number, velocity: number): void {
    this.synth?.noteOn(channel, note, velocity);
  }

  noteOff(channel: number, note: number): void {
    this.synth?.noteOff(channel, note);
  }

  programChange(channel: number, program: number): void {
    this.synth?.programChange(channel, program);
  }

  controllerChange(channel: number, controller: number, value: number): void {
    this.synth?.sendMessage([0xb0 | channel, controller & 0x7f, value & 0x7f]);
  }

  /** Set a channel's pitch bend from a cents offset. */
  pitchBendCents(channel: number, cents: number): void {
    this.synth?.pitchWheel(channel, centsToPitchWheel(cents));
  }

  /** All notes off on every channel (panic / disconnect / tab hidden). */
  allNotesOff(): void {
    const synth = this.synth;
    if (!synth) return;
    for (const ch of ALL_CHANNELS) {
      synth.sendMessage([0xb0 | ch, 123, 0]); // CC123 All Notes Off
    }
  }

  // --- Check A helper: play one note for a fixed duration ---

  /** Play a single note (default: Acoustic Grand Piano, middle C) for durationMs. */
  playTestNote(
    note = 60,
    { program = 0, velocity = 100, durationMs = 700, channel = 0 } = {},
  ): void {
    if (!this.synth) return;
    this.programChange(channel, program);
    this.noteOn(channel, note, velocity);
    window.setTimeout(() => this.noteOff(channel, note), durationMs);
  }
}
