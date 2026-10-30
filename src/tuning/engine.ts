// RESULTS_v3 rule tuning engine (handoff section 7). Computes a per-note pitch
// offset in cents: part-role offset + step-down + (optional) leap-down + a
// long-note flattening ramp, all scaled by `scale`, plus a shared slow drift
// (not scaled). The integration contract (handoff 11.4) lives here: `offset()`.
//
// Definitions follow ~/Desktop/Research/RESULTS_v3_virtuoso_strings.md:
//   step down  = approached from above by 1-2 semitones  (+3)
//   leap down  = approached from above by >= 5 semitones  (-2.5, off by default)
//   long note  = held >= 1 s  (ramps to -3)
// The 3-4 semitone downward interval is neither (no measured effect), so it gets
// no step/leap term. This leap threshold (>=5) is the one change from the handoff
// defaults (which implied >=3); told to Sophie.

import type { AppConfig, Role } from "../state/config";

export type Approach = "none" | "step" | "leap";

export const LEAP_MIN_SEMITONES = 5;

/** The per-voice fields the offset math needs. The engine's Voice satisfies this. */
export interface VoiceState {
  role: Role;
  approach: Approach;
  t0: number; // performance.now() at note-on
}

export interface Breakdown {
  role: number;
  step: number;
  leap: number;
  long: number;
  drift: number;
  total: number;
}

const ZERO: Breakdown = { role: 0, step: 0, leap: 0, long: 0, drift: 0, total: 0 };

// Standard normal via Box-Muller.
function gaussian(): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export class TuningEngine {
  private getConfig: () => AppConfig;
  private drift: number;
  private petalPrev = new Map<number, { note: number; time: number }>();

  constructor(getConfig: () => AppConfig) {
    this.getConfig = getConfig;
    this.drift = getConfig().tuning.drift.initialCents;
  }

  get driftCents(): number {
    return this.drift;
  }

  /** Reset the drift to its starting value (on mode switch or audio restart). */
  resetDrift(): void {
    this.drift = this.getConfig().tuning.drift.initialCents;
  }

  /**
   * Classify a new note's approach from the petal's previous note, then record
   * this note as the petal's new previous note (handoff 7.4). Call once, at
   * note-on, using the intended target note (before tuning).
   */
  classifyApproach(petal: number, target: number, now: number): Approach {
    const t = this.getConfig().tuning;
    const prev = this.petalPrev.get(petal);
    let approach: Approach = "none";
    if (prev && (now - prev.time) / 1000 <= t.stepDown.windowSec) {
      const d = prev.note - target; // positive => the new note is lower
      if (d >= 1 && d <= t.stepDown.maxSemitones) approach = "step";
      else if (d >= LEAP_MIN_SEMITONES) approach = "leap";
    }
    this.petalPrev.set(petal, { note: target, time: now });
    return approach;
  }

  /** Advance the shared drift (Ornstein-Uhlenbeck) by real dt seconds. */
  tickDrift(dtSec: number): void {
    const d = this.getConfig().tuning.drift;
    if (!d.enabled || dtSec <= 0) return;
    this.drift +=
      (-this.drift / d.tauSec) * dtSec + d.sigmaCents * Math.sqrt((2 * dtSec) / d.tauSec) * gaussian();
    this.drift = Math.max(-d.clampCents, Math.min(d.clampCents, this.drift));
  }

  /** The offset breakdown for a voice at time `now`. Components are post-scale so
   *  they sum to `total` (drift is added unscaled, per the model). */
  breakdown(v: VoiceState, now: number): Breakdown {
    const t = this.getConfig().tuning;
    if (t.mode === "equal") return { ...ZERO };

    const role = t.roleOffsets[v.role] ?? 0;
    const step = t.stepDown.enabled && v.approach === "step" ? t.stepDown.cents : 0;
    const leap = t.leapDown.enabled && v.approach === "leap" ? t.leapDown.cents : 0;

    let long = 0;
    if (t.longNote.enabled) {
      const held = (now - v.t0) / 1000;
      const span = t.longNote.fullSec - t.longNote.startSec;
      const frac = span > 0 ? Math.max(0, Math.min(1, (held - t.longNote.startSec) / span)) : 0;
      long = t.longNote.cents * frac;
    }

    const scale = t.scale;
    const drift = t.drift.enabled ? this.drift : 0;
    return {
      role: role * scale,
      step: step * scale,
      leap: leap * scale,
      long: long * scale,
      drift,
      total: (role + step + leap + long) * scale + drift,
    };
  }

  offset(v: VoiceState, now: number): number {
    return this.breakdown(v, now).total;
  }
}
