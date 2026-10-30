// Hub note/channel mapping (handoff 1.2) and its inverse.
//
// The current hub firmware walks up the C-major scale: for (petalId, key) it
// emits a MIDI note computed from the formula below, on a per-petal channel.
// The app inverts (channel, note) -> (petal, key) so that with zero config it
// plays exactly what the hub plays today.

const MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11];
export const KEYS_PER_PETAL = 6;

/** The MIDI note the current hub firmware emits for (petalId, key). */
export function noteFor(id: number, k: number): number {
  const step = (id - 1) * KEYS_PER_PETAL + k;
  let n = 60 + 12 * Math.floor(step / 7) + MAJOR_SCALE[step % 7];
  while (n > 96) n -= 36;
  return n;
}

/** 1-based MIDI channel the hub uses for a petal (petal 1 -> channel 1; wraps past 16). */
export function hubChannelFor(id: number): number {
  return ((id - 1) % 16) + 1;
}

export interface PetalKey {
  petal: number;
  key: number;
}

// Inversion map: `${channel1based}:${note}` -> { petal, key }. Built for petals
// with unique channels (1..16). Within one petal the six notes are distinct, so
// (channel, note) is unambiguous. Petals >16 reuse channels on the real bus and
// are intentionally not inverted here (the app's main view is petals 1..6).
const INVERT_MAX_PETAL = 16;
const inversion = new Map<string, PetalKey>();
for (let id = 1; id <= INVERT_MAX_PETAL; id++) {
  const ch = hubChannelFor(id);
  for (let k = 0; k < KEYS_PER_PETAL; k++) {
    inversion.set(`${ch}:${noteFor(id, k)}`, { petal: id, key: k });
  }
}

/** Recover (petal, key) from a hub (1-based channel, note). null if unknown. */
export function invertHubTable(channel1based: number, note: number): PetalKey | null {
  return inversion.get(`${channel1based}:${note}`) ?? null;
}

/** Petal id for a 1-based hub channel (for CC messages that carry no note). */
export function petalFromChannel(channel1based: number): number {
  return channel1based; // identity for channels 1..16 (the app's range)
}
