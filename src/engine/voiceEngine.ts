// Voice engine (handoff section 6): consumes the hub's raw MIDI stream, inverts
// the hub table to (petal, key), applies the user's config, and plays each
// sounding note on its own channel (channel rotation) through the SoundEngine.
// Pitch offsets come from the RESULTS_v3 tuning engine (section 7); a 20 ms tick
// advances drift + the long-note ramp and re-sends pitch bend when it moves.

import { type AppConfig, type ExpressionMode, type PetalConfig, type Role } from "../state/config";
import { configStore } from "../state/store";
import { invertHubTable, petalFromChannel } from "../midi/hubTable";
import { SoundEngine, VOICE_CHANNELS } from "../audio/soundEngine";
import { isPresent, setKeyDown, setPressure } from "../state/liveState";
import { computeRoles } from "../tuning/roles";
import { type Approach, TuningEngine } from "../tuning/engine";
import { removeReadoutRow, setDrift, setReadoutRow } from "../tuning/readout";
import { appendLogRow, isLogEnabled } from "../devhub/eventLog";

const DIGITAL_KEY = 5; // key 6 (A) is on/off only (handoff 2.2)

interface Voice {
  petal: number;
  key: number;
  targetNote: number;
  channel: number; // 0-based MIDI channel in the synth
  t0: number;
  role: Role;
  approach: Approach;
  sentCents: number; // last pitch-bend value sent, in cents
  // Captured at note-on for the event log (handoff 7.6):
  velHub: number;
  velApp: number;
  instrument: string;
  onEpochMs: number;
  onRoleCents: number;
  onStepCents: number;
  onTotalCents: number;
}

const voiceKey = (petal: number, key: number) => `${petal}:${key}`;

export class VoiceEngine {
  private engine: SoundEngine;
  private freeChannels: number[]; // LRU: front = least recently released
  private channelProgram = new Map<number, number>();
  private channelBank = new Map<number, number>();
  private voices = new Map<string, Voice>();
  private petalPressure = new Map<number, number>();
  private tuning: TuningEngine;
  private tickHandle: ReturnType<typeof setInterval>;
  private lastTick = performance.now();
  private lastMode: "equal" | "ensemble";

  constructor(engine: SoundEngine) {
    this.engine = engine;
    this.freeChannels = [...VOICE_CHANNELS];
    this.tuning = new TuningEngine(() => configStore.get());
    this.lastMode = configStore.get().tuning.mode;
    this.tickHandle = setInterval(() => this.tick(), 20);
  }

  dispose() {
    clearInterval(this.tickHandle);
  }

  private cfg(): AppConfig {
    return configStore.get();
  }
  private petalCfg(id: number): PetalConfig {
    return configStore.ensurePetal(id);
  }

  /** Entry point for a raw 3-byte MIDI message from the hub (real or virtual). */
  handleMidi(bytes: number[] | Uint8Array) {
    const status = bytes[0];
    const cmd = status & 0xf0;
    const ch1 = (status & 0x0f) + 1;
    switch (cmd) {
      case 0x90:
        if (bytes[2] > 0) this.noteOn(ch1, bytes[1], bytes[2]);
        else this.noteOffMsg(ch1, bytes[1]);
        break;
      case 0x80:
        this.noteOffMsg(ch1, bytes[1]);
        break;
      case 0xb0:
        this.controlChange(ch1, bytes[1], bytes[2]);
        break;
      case 0xa0:
        this.polyAftertouch(ch1, bytes[1], bytes[2]);
        break;
    }
  }

  private allocateChannel(bank: number, program: number): number {
    if (this.freeChannels.length === 0) {
      // Steal the oldest sounding voice (sends its Note Off, frees its channel).
      let oldest: Voice | undefined;
      for (const v of this.voices.values()) if (!oldest || v.t0 < oldest.t0) oldest = v;
      if (oldest) this.releaseVoice(oldest, true);
    }
    // Prefer a free channel already set to this bank+program (avoids a program change).
    let idx = this.freeChannels.findIndex(
      (c) => this.channelProgram.get(c) === program && (this.channelBank.get(c) ?? 0) === bank,
    );
    if (idx === -1) idx = 0; // otherwise least-recently-released
    const ch = this.freeChannels.splice(idx, 1)[0];
    return ch ?? VOICE_CHANNELS[0];
  }

  private remapVelocity(v: number, k: number): number {
    const feel = this.cfg().feel;
    if (k === DIGITAL_KEY) return feel.digitalKeyVelocity;
    const x = Math.max(0, Math.min(1, (v - 90) / 37));
    return Math.round(feel.velocityFloor + (127 - feel.velocityFloor) * Math.pow(x, feel.velocityCurve));
  }

  private pressureToCC(p: number, mode: ExpressionMode): number {
    if (mode === "fixed") return 127;
    const feel = this.cfg().feel;
    return Math.round(feel.pressureFloor + (127 - feel.pressureFloor) * (p / 127));
  }

  private roleFor(petal: number): Role {
    const config = this.cfg();
    const presentIds = Object.keys(config.petals).map(Number).filter(isPresent);
    return computeRoles(config, presentIds).get(petal) ?? "solo";
  }

  private noteOn(ch1: number, note: number, velocity: number) {
    const inv = invertHubTable(ch1, note);
    if (!inv) {
      console.debug("Tunagon: unknown (channel, note)", ch1, note);
      return;
    }
    const { petal, key } = inv;
    setKeyDown(petal, key, true); // UI lights even for silent keys

    const cfg = this.petalCfg(petal);
    const target = cfg.keys[key];
    if (target == null) return; // silent key: no sound

    const now = performance.now();
    const velApp = this.remapVelocity(velocity, key);
    const program = cfg.instrument.program;
    const bank = cfg.instrument.bank ?? 0;
    const channel = this.allocateChannel(bank, program);

    // Role (from present petals' ranges) and approach are fixed at note-on.
    const role = this.roleFor(petal);
    const approach = this.tuning.classifyApproach(petal, target, now);
    const voice: Voice = {
      petal,
      key,
      targetNote: target,
      channel,
      t0: now,
      role,
      approach,
      sentCents: 0,
      velHub: velocity,
      velApp,
      instrument: cfg.instrument.name,
      onEpochMs: Date.now(),
      onRoleCents: 0,
      onStepCents: 0,
      onTotalCents: 0,
    };
    const bdOn = this.tuning.breakdown(voice, now);
    voice.sentCents = bdOn.total;
    voice.onRoleCents = bdOn.role;
    voice.onStepCents = bdOn.step;
    voice.onTotalCents = bdOn.total;

    // Order matters (handoff 6.2): program -> volume/pan -> bend -> CC11 -> Note On.
    // Non-GM instruments (e.g. Ukulele = bank 8) need a Bank Select (CC0) before
    // the program change; GeneralUser GS selects its variations that way.
    if (this.channelProgram.get(channel) !== program || (this.channelBank.get(channel) ?? 0) !== bank) {
      this.engine.controllerChange(channel, 0, bank); // CC0 bank select
      this.engine.programChange(channel, program);
      this.channelBank.set(channel, bank);
      this.channelProgram.set(channel, program);
    }
    this.engine.controllerChange(channel, 7, Math.round(cfg.volume * 127)); // CC7 volume
    this.engine.controllerChange(channel, 10, Math.round(((cfg.pan + 1) / 2) * 127)); // CC10 pan
    this.engine.pitchBendCents(channel, bdOn.total);
    const pressure = this.petalPressure.get(petal) ?? 0;
    this.engine.controllerChange(channel, 11, this.pressureToCC(pressure, cfg.expressionMode));
    this.engine.noteOn(channel, target, velApp);

    this.voices.set(voiceKey(petal, key), voice);
    setReadoutRow({
      voiceKey: voiceKey(petal, key),
      petal,
      key,
      note: target,
      role,
      approach,
      breakdown: bdOn,
    });
  }

  private noteOffMsg(ch1: number, note: number) {
    const inv = invertHubTable(ch1, note);
    if (!inv) return;
    const { petal, key } = inv;
    setKeyDown(petal, key, false);
    const voice = this.voices.get(voiceKey(petal, key));
    if (voice) this.releaseVoice(voice, false);
  }

  private releaseVoice(voice: Voice, immediate: boolean) {
    const now = performance.now();
    this.engine.noteOff(voice.channel, voice.targetNote);
    this.voices.delete(voiceKey(voice.petal, voice.key));
    removeReadoutRow(voiceKey(voice.petal, voice.key));

    if (isLogEnabled()) {
      const bdOff = this.tuning.breakdown(voice, now);
      appendLogRow({
        time_ms: voice.onEpochMs,
        petal: voice.petal,
        key: voice.key,
        note: voice.targetNote,
        velocity_hub: voice.velHub,
        velocity_app: voice.velApp,
        role: voice.role,
        approach: voice.approach,
        role_cents: voice.onRoleCents,
        step_cents: voice.onStepCents,
        long_cents_at_off: bdOff.long,
        drift_cents: this.tuning.driftCents,
        total_cents_at_on: voice.onTotalCents,
        total_cents_at_off: bdOff.total,
        duration_ms: Math.round(now - voice.t0),
        instrument: voice.instrument,
      });
    }

    // Hold the channel out of the pool briefly so its release tail isn't retuned
    // by the next note on that channel (handoff 6.2).
    const giveBack = () => {
      if (!this.freeChannels.includes(voice.channel)) this.freeChannels.push(voice.channel);
    };
    if (immediate) giveBack();
    else setTimeout(giveBack, 50);
  }

  private controlChange(ch1: number, cc: number, value: number) {
    if (cc !== 11 && cc !== 1) return; // CC11 expression / CC1 mod = per-petal pressure
    const petal = petalFromChannel(ch1);
    this.petalPressure.set(petal, value);
    setPressure(petal, value);
    const cfg = this.petalCfg(petal);
    if (cfg.expressionMode !== "swell") return;
    const cc11 = this.pressureToCC(value, "swell");
    for (const voice of this.voices.values()) {
      if (voice.petal === petal) this.engine.controllerChange(voice.channel, 11, cc11);
    }
  }

  // Per-key pressure (arrives from the real hub after the Phase-1 firmware change).
  private polyAftertouch(ch1: number, note: number, value: number) {
    const inv = invertHubTable(ch1, note);
    if (!inv) return;
    const voice = this.voices.get(voiceKey(inv.petal, inv.key));
    if (!voice) return;
    setPressure(inv.petal, value);
    const cfg = this.petalCfg(inv.petal);
    if (cfg.expressionMode === "swell") {
      this.engine.controllerChange(voice.channel, 11, this.pressureToCC(value, "swell"));
    }
  }

  /** 20 ms engine tick (handoff 7.5): advance drift + the long-note ramp,
   *  re-send pitch bend for voices whose offset moved >= 0.05 cents, refresh the
   *  readout. Resets drift when the tuning mode is switched. */
  private tick() {
    const now = performance.now();
    const dt = (now - this.lastTick) / 1000;
    this.lastTick = now;

    const mode = this.cfg().tuning.mode;
    if (mode !== this.lastMode) {
      this.tuning.resetDrift();
      this.lastMode = mode;
    }
    this.tuning.tickDrift(dt);

    for (const voice of this.voices.values()) {
      const bd = this.tuning.breakdown(voice, now);
      if (Math.abs(bd.total - voice.sentCents) >= 0.05) {
        this.engine.pitchBendCents(voice.channel, bd.total);
        voice.sentCents = bd.total;
      }
      setReadoutRow({
        voiceKey: voiceKey(voice.petal, voice.key),
        petal: voice.petal,
        key: voice.key,
        note: voice.targetNote,
        role: voice.role,
        approach: voice.approach,
        breakdown: bd,
      });
    }
    setDrift(this.tuning.driftCents);
  }

  /** Release a petal's sounding voices — called when its keys or instrument
   *  change, so no note is stuck on an old pitch/instrument (handoff 5.2). */
  releasePetal(petalId: number) {
    for (const voice of [...this.voices.values()]) {
      if (voice.petal === petalId) this.releaseVoice(voice, true);
    }
  }

  /** Stop everything (panic / disconnect / tab hidden). */
  panic() {
    for (const voice of [...this.voices.values()]) this.releaseVoice(voice, true);
    this.engine.allNotesOff();
  }
}
