// Scale presets for the editor's "Fill keys" (handoff 5.1 / 13).

export const PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export interface ScaleDef {
  id: string;
  name: string;
  intervals: number[]; // semitone offsets from the root, one octave
}

export const SCALES: ScaleDef[] = [
  { id: "major", name: "Major", intervals: [0, 2, 4, 5, 7, 9, 11] },
  { id: "natural_minor", name: "Natural minor", intervals: [0, 2, 3, 5, 7, 8, 10] },
  { id: "harmonic_minor", name: "Harmonic minor", intervals: [0, 2, 3, 5, 7, 8, 11] },
  { id: "dorian", name: "Dorian", intervals: [0, 2, 3, 5, 7, 9, 10] },
  { id: "mixolydian", name: "Mixolydian", intervals: [0, 2, 4, 5, 7, 9, 10] },
  { id: "major_pentatonic", name: "Major pentatonic", intervals: [0, 2, 4, 7, 9] },
  { id: "minor_pentatonic", name: "Minor pentatonic", intervals: [0, 3, 5, 7, 10] },
  { id: "blues", name: "Blues", intervals: [0, 3, 5, 6, 7, 10] },
  { id: "whole_tone", name: "Whole tone", intervals: [0, 2, 4, 6, 8, 10] },
  { id: "chromatic", name: "Chromatic", intervals: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] },
];

/** Six ascending notes from (rootPc, octave) up the scale, wrapping octaves. */
export function fillScale(rootPc: number, octave: number, intervals: number[], count = 6): number[] {
  const rootMidi = (octave + 1) * 12 + rootPc; // C(-1)=0, so C4=60
  const out: number[] = [];
  for (let i = 0; i < count; i++) {
    const degree = intervals[i % intervals.length];
    const octaveShift = Math.floor(i / intervals.length);
    out.push(rootMidi + degree + 12 * octaveShift);
  }
  return out;
}
