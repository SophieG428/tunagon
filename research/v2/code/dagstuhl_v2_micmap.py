#!/usr/bin/env python
"""Dagstuhl v2: recover v1 per-track mic assignment from the v1 log table,
map each of the 108 tracks to a wav in audio_wav_22050_mono (same mic as v1
uniform; for the 7 tracks with no shipped pYIN, pick by LRX > HSM > DYN among
available wavs), verify existence against the Desktop filename listing, and
emit (a) the fetch list of absolute Desktop paths, (b) a JSON track->wav map.
"""
import json, os, re, sys

ROOT = "/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run"
LOG = os.path.join(ROOT, "logs", "dagstuhl_agent.md")
WAVLIST = os.path.join(ROOT, "code", "wav_listing.txt")
DESKTOP_AUDIO = ("<path to your datasets folder>/"
                 "Dagstuhl ChoirSet/DagstuhlChoirSet_V1.2.2/audio_wav_22050_mono")
PREF = ["LRX", "HSM", "DYN"]

rows = []
in_table = False
for line in open(LOG):
    line = line.strip()
    if line.startswith("| take_id | singer | best_source"):
        in_table = True
        continue
    if in_table:
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5:
            sys.exit(f"bad table row: {line}")
        rows.append(dict(take_id=cells[0], singer=cells[1], best_source=cells[2],
                         mic_uniform=cells[3], mic_best=cells[4]))

assert len(rows) == 108, f"expected 108 rows, got {len(rows)}"

wavs = set(l.strip() for l in open(WAVLIST) if l.strip())

track_map = {}
fetch = []
problems = []
filled = []
for r in rows:
    tid, singer = r["take_id"], r["singer"]
    key = f"{tid}_{singer}"
    if r["mic_uniform"] != "-":
        mic = r["mic_uniform"]
        chosen_by = "v1_uniform_mic"
        wav = f"{tid}_{singer}_{mic}.wav"
        if wav not in wavs:
            problems.append(f"MISSING wav for v1 mic: {wav}")
            continue
    else:
        # 7 tracks with no shipped pYIN: pick by LRX > HSM > DYN among available wavs
        mic = None
        for cand in PREF:
            if f"{tid}_{singer}_{cand}.wav" in wavs:
                mic = cand
                break
        if mic is None:
            problems.append(f"NO wav at any mic for previously-missing track: {key}")
            continue
        chosen_by = "pref_rule_fill"
        wav = f"{tid}_{singer}_{mic}.wav"
        filled.append(f"{key} -> {mic}")
    track_map[key] = dict(take_id=tid, performer_id=singer, part=singer[0],
                          mic=mic, wav=wav, chosen_by=chosen_by,
                          v1_mic_uniform=r["mic_uniform"], mic_best=r["mic_best"],
                          best_source=r["best_source"])
    fetch.append(os.path.join(DESKTOP_AUDIO, wav))

print(f"tracks mapped: {len(track_map)}/108")
print(f"previously-missing tracks filled ({len(filled)}): " + "; ".join(filled))
from collections import Counter
print("mic counts:", Counter(t["mic"] for t in track_map.values()))
if problems:
    print("PROBLEMS:")
    for p in problems:
        print(" ", p)
    sys.exit(1)

with open(os.path.join(ROOT, "code", "dagstuhl_v2_fetch_list.txt"), "w") as f:
    f.write("\n".join(fetch) + "\n")
with open(os.path.join(ROOT, "code", "dagstuhl_v2_track_map.json"), "w") as f:
    json.dump(track_map, f, indent=1, sort_keys=True)
print("wrote fetch list and track map")
