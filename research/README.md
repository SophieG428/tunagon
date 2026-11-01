# Tuneagon tuning research

This folder holds the research behind the app's **Ensemble** tuning mode: how real ensembles bend pitch away from equal temperament, and the code used to measure it. The app's tuning engine (`src/tuning/`) is built directly from the v3 findings below.

## What's here

| Folder | What it is |
|---|---|
| `v3/` | **The findings the app uses.** Note-by-note pitch analysis of a professional string quartet (24 takes of the Haydn Op. 74/1 finale). `RESULTS_v3_virtuoso_strings.md` is the summary; `vs_notes_v3.csv` is the measured note table (10,850 notes). |
| `v2/code/` | Second round: detrended pitch, real-time (causal) features, partner-coupling analysis, and dataset rebuild scripts. |
| `v1/code/` | First round: feature extraction and the train/evaluate protocol (gradient-boosted trees + ridge, cross-validated). |
| `notebooks/` | The Google Colab notebooks that ran v1 and v2. |

## Main findings

- **v1/v2 (machine learning):** after removing each take's slow drift, plain equal temperament predicted note-by-note pitch about as well as or better than the trained models and a just-intonation rule. Chord context didn't help.
- **v3 (string quartet, measured directly):**
  - Each part has a consistent offset: 1st violin about **+10 cents** sharp, 2nd violin about −5, viola about −6, cello about −1.
  - Notes approached by a **step down land sharp** (about +4 cents), matching every earlier ensemble studied.
  - Long held notes sit flatter (about −3 cents); open strings sit about −2 cents.
  - No detectable short-term "pitch following" between players inside a take.

The Ensemble mode applies these effects as pitch bend per note; the app's scale slider (×0.5–×5) exaggerates them so they're easy to hear.

## Data and licenses

- `v3/vs_notes_v3.csv` is derived from the **ARME Virtuoso Strings** dataset (github.com/arme-project/virtuoso-strings), licensed **CC BY-NC-SA 4.0**. This derived table is shared under the same license, for non-commercial use with attribution. The audio is not included.
- The v1/v2 code was also run on the public choir datasets **Dagstuhl ChoirSet**, **ESMUC Choir Dataset** and **Choral Singing Dataset**. Their data is not included here; get it from the original sources.
- One additional dataset used in v1/v2 is licensed for internal use only. None of its data, or code specific to it, is in this repository.
