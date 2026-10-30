// Voice-role assignment from configured note ranges (handoff 7.3). Used by the
// editor display now and by the tuning engine in a later step.

import type { AppConfig, PetalConfig, Role } from "../state/config";

/** Mean of a petal's non-null key notes, or null if the petal is all silent. */
export function rangeCenter(cfg: PetalConfig): number | null {
  const notes = cfg.keys.filter((n): n is number => n != null);
  if (notes.length === 0) return null;
  return notes.reduce((a, b) => a + b, 0) / notes.length;
}

/**
 * Roles over the present petals (or all configured petals if none are present),
 * considering only petals that have a note range. Highest range = top, lowest =
 * bass, the rest inner; exactly one = solo. Ties: lower petal id takes the higher
 * role. `roleOverride` replaces the auto result for that petal only.
 */
export function computeRoles(config: AppConfig, presentIds: number[]): Map<number, Role> {
  const roles = new Map<number, Role>();

  const withRange = (ids: number[]) =>
    ids.filter((id) => config.petals[id] && rangeCenter(config.petals[id]) != null);

  let ids = withRange(presentIds);
  if (ids.length === 0) ids = withRange(Object.keys(config.petals).map(Number));

  ids.sort((a, b) => {
    const ca = rangeCenter(config.petals[a])!;
    const cb = rangeCenter(config.petals[b])!;
    if (cb !== ca) return cb - ca; // higher range first
    return a - b; // tie: lower id first
  });

  if (ids.length === 1) {
    roles.set(ids[0], "solo");
  } else if (ids.length >= 2) {
    roles.set(ids[0], "top");
    roles.set(ids[ids.length - 1], "bass");
    for (let i = 1; i < ids.length - 1; i++) roles.set(ids[i], "inner");
  }

  // Per-petal overrides replace the auto result.
  for (const idStr of Object.keys(config.petals)) {
    const id = Number(idStr);
    const ov = config.petals[id].roleOverride;
    if (ov !== "auto") roles.set(id, ov);
  }
  return roles;
}
