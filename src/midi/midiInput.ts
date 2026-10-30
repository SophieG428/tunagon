// Web MIDI input (handoff 3.1, 5.1): connects to the real hub and routes its
// MIDI into the same handler the virtual hub uses, so the engine can't tell them
// apart. Auto-selects the "Daisy" input, remembers the choice, re-scans on
// plug/unplug, and fires onDisconnect (all notes off) when the hub goes away.

import { useSyncExternalStore } from "react";

export type MidiStatusKind = "idle" | "unsupported" | "denied" | "no-device" | "connected";

export interface MidiInputSnapshot {
  supported: boolean;
  statusKind: MidiStatusKind;
  connectedName: string | null;
  inputs: { id: string; name: string }[];
  selectedId: string | null;
}

type Handler = (bytes: Uint8Array) => void;

const STORAGE_KEY = "tunagon.midiInputName";

class MidiInputManager {
  private access: MIDIAccess | null = null;
  private handler: Handler | null = null;
  private onDisconnect: (() => void) | null = null;
  private selectedId: string | null = null;
  private boundInput: MIDIInput | null = null;
  private listeners = new Set<() => void>();
  private readonly supported =
    typeof navigator !== "undefined" && typeof navigator.requestMIDIAccess === "function";
  private snapshot: MidiInputSnapshot;

  constructor() {
    this.snapshot = {
      supported: this.supported,
      statusKind: this.supported ? "idle" : "unsupported",
      connectedName: null,
      inputs: [],
      selectedId: null,
    };
  }

  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
    };
  };

  getSnapshot = (): MidiInputSnapshot => this.snapshot;

  private emit(patch: Partial<MidiInputSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const l of this.listeners) l();
  }

  /** Request MIDI access (triggers Chrome's one-time permission prompt) and start
   *  listening. Call from a user gesture. Safe to call more than once. */
  async init(handler: Handler, onDisconnect: () => void) {
    this.handler = handler;
    this.onDisconnect = onDisconnect;
    if (!this.supported) {
      this.emit({ statusKind: "unsupported" });
      return;
    }
    if (this.access) {
      this.scan();
      return;
    }
    try {
      this.access = await navigator.requestMIDIAccess({ sysex: true });
    } catch (e) {
      console.warn("Tunagon: MIDI access denied or unavailable.", e);
      this.emit({ statusKind: "denied" });
      return;
    }
    this.access.onstatechange = () => this.scan();
    this.scan();
  }

  private listInputs(): { id: string; name: string }[] {
    const out: { id: string; name: string }[] = [];
    this.access?.inputs.forEach((inp) => out.push({ id: inp.id, name: inp.name ?? inp.id }));
    return out;
  }

  /** Recompute which input should be active and (re)bind to it. */
  private scan() {
    const inputs = this.listInputs();

    let selId =
      this.selectedId && inputs.some((i) => i.id === this.selectedId) ? this.selectedId : null;
    if (!selId) {
      const remembered = localStorage.getItem(STORAGE_KEY);
      if (remembered) selId = inputs.find((i) => i.name === remembered)?.id ?? null;
    }
    if (!selId) {
      selId = inputs.find((i) => /daisy/i.test(i.name))?.id ?? null;
    }

    this.applySelection(selId);

    const name = selId ? (inputs.find((i) => i.id === selId)?.name ?? null) : null;
    if (name) localStorage.setItem(STORAGE_KEY, name);
    this.emit({
      inputs,
      selectedId: selId,
      connectedName: name,
      statusKind: selId ? "connected" : "no-device",
    });
  }

  private applySelection(selId: string | null) {
    // Moving away from a bound input (manual switch, or the hub was unplugged):
    // detach it and raise all-notes-off.
    if (this.boundInput && this.boundInput.id !== selId) {
      this.boundInput.onmidimessage = null;
      this.boundInput = null;
      this.onDisconnect?.();
    }
    this.selectedId = selId;
    if (!selId || !this.access) return;
    if (this.boundInput?.id === selId) return;

    const inp = this.access.inputs.get(selId);
    if (!inp) {
      this.boundInput = null;
      return;
    }
    inp.onmidimessage = (e: MIDIMessageEvent) => {
      if (e.data && this.handler) this.handler(e.data);
    };
    this.boundInput = inp;
  }

  /** Manual choice from the dropdown. */
  selectInput(id: string) {
    const inputs = this.listInputs();
    const name = inputs.find((i) => i.id === id)?.name ?? null;
    if (name) localStorage.setItem(STORAGE_KEY, name);
    this.applySelection(id);
    this.emit({ selectedId: id, connectedName: name, statusKind: id ? "connected" : "no-device" });
  }
}

export const midiInput = new MidiInputManager();

export function useMidiInput(): MidiInputSnapshot {
  return useSyncExternalStore(midiInput.subscribe, midiInput.getSnapshot);
}
