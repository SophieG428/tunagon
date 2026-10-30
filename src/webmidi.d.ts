// Minimal Web MIDI API types (not in the standard TS DOM lib). Only what the
// app uses. https://www.w3.org/TR/webmidi/

interface MIDIOptions {
  sysex?: boolean;
  software?: boolean;
}

interface MIDIMessageEvent extends Event {
  readonly data: Uint8Array;
}

interface MIDIPort extends EventTarget {
  readonly id: string;
  readonly name: string | null;
  readonly manufacturer: string | null;
  readonly state: "connected" | "disconnected";
  readonly connection: "open" | "closed" | "pending";
}

interface MIDIInput extends MIDIPort {
  onmidimessage: ((e: MIDIMessageEvent) => void) | null;
}

interface MIDIOutput extends MIDIPort {
  send(data: number[] | Uint8Array, timestamp?: number): void;
}

interface MIDIInputMap {
  readonly size: number;
  get(id: string): MIDIInput | undefined;
  forEach(cb: (value: MIDIInput, key: string, map: MIDIInputMap) => void): void;
  values(): IterableIterator<MIDIInput>;
}

interface MIDIOutputMap {
  readonly size: number;
  get(id: string): MIDIOutput | undefined;
  forEach(cb: (value: MIDIOutput, key: string, map: MIDIOutputMap) => void): void;
  values(): IterableIterator<MIDIOutput>;
}

interface MIDIAccess extends EventTarget {
  readonly inputs: MIDIInputMap;
  readonly outputs: MIDIOutputMap;
  onstatechange: ((e: Event) => void) | null;
}

interface Navigator {
  requestMIDIAccess(options?: MIDIOptions): Promise<MIDIAccess>;
}
