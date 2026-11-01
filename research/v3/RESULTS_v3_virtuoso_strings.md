# Adaptive Tuning — v3: professional string quartet (Virtuoso Strings, Haydn Op.74/1 finale)
Data: ARME Virtuoso Strings, Q-JH-VN1-NR + Q-JH-VN2-NR, 24 takes x 4 close-miked players, ~45 s each.
Pipeline: CONTRACT pYIN (sr 22050, hop 256, res 0.05), median voiced F0 over central 70% of each annotated note;
pitch label = consensus across 24 takes (93% agreement); kept 10,850 notes. rel = dev minus median of OTHER parts within ±6 s.
CIs: 95% take-level bootstrap, seed 20260813. Grid caveat: pYIN 5-cent grid phase differs between violins and viola/cello by ~2 c.

## Part offsets vs the rest of the quartet (cents)
VN1 +9.7 [+9.0,+10.5] | VN2 -4.6 [-5.4,-4.0] | VA -6.1 [-7.0,-5.2] | VC -1.0 [-2.1,+0.2]
Same whichever violin leads (VN1 +10.1 vs +9.4).

## Note-level effects (rel, cents)
- Step down (m2 -1 / M2 -2): +3.6 / +4.0  (matches all three earlier ensembles: approached-from-above notes land sharp)
- Leap down >=5: -2.5 ; leap up >=5: +1.3 ; step up m2: -0.7 ; repeated: -0.6
- High in part's range (>=+5 st): +1.9 (opposite of the choirs, which go flat high)
- Long notes >=1 s: -3.2 ; short <0.3 s: +1.0
- Open-string pitches: -2.1 vs stopped
- Louder notes: -0.2 per SD (nothing)
- Major-chord 3rds held >=0.5 s: -1.9 [-3.8,+0.1] (n=64); held >=1 s: -10.7 (n=24, one spot in the score, VN2) — JI predicts -13.7. No minor chords to compare.

## Drift
Whole-ensemble level: start ~+1.5 c vs A440, median drift ~0 c/min, 12/24 takes flat-going, range -6.6..+6.2 c/min. No trend across takes.
Per-part slopes (VC +11, VN2 +5.5, VN1 -2.5 c/min) repeat across takes = shaped by the piece, not wandering.

## Coupling
Naive "gap closing" (34–79% per 2 s) is regression-to-the-mean artifact. Controlling own previous level, weight on others' level 2 s
earlier is ~0 or negative (VN1 -0.04, VN2 -0.10, VA -0.18, VC -0.29). No detectable short-term pitch following inside 45-s takes.
