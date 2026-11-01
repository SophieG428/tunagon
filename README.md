# Tunagon App

Web app (Chrome) that controls the Tunagon modular instrument: shows the petals
that are plugged into the hub, lets you set each petal's instrument and the note
on each of its 6 keys, plays built-in sounds, and applies the **Adaptive Tuning**
research engine. Built per `../Tunagon_App_Handoff.md`.

## Run it (dev)

```bash
npm install
npm run dev
```

Then open **http://localhost:5173** in **Chrome**. `localhost` is a secure
context, so Web MIDI and Web Audio work without HTTPS.

> **Audio needs a click.** Browsers block audio until a user gesture, so the app
> shows a **Start audio** button. The first click loads the GeneralUser GS
> SoundFont (~31 MB) once; the browser caches it afterwards.

## Build / preview (production)

```bash
npm run build     # type-checks (tsc) then builds to dist/
npm run preview
```

`vite.config.ts` sets `base: './'` so the same build works both at the dev
`localhost` root and under a GitHub Pages project subpath — no repo name is
hard-coded. (Hosting on GitHub Pages is the chosen target; we push at the end of
Phase 1.)

## Layout

```
public/soundfonts/GeneralUser-GS.sf2    bundled SoundFont (GeneralUser GS 2.0.3)
public/soundfonts/GeneralUser-GS.LICENSE.txt
src/audio/soundEngine.ts                spessasynth_lib wrapper (synth + audio graph)
src/App.tsx                             UI
```

## Sound

- Synth: `spessasynth_lib` v4.4.1 (`WorkletSynthesizer`, SF2 in an AudioWorklet).
- Sound bank: **GeneralUser GS 2.0.3** — all 128 General MIDI instruments.
  License (`public/soundfonts/GeneralUser-GS.LICENSE.txt`) permits free use and
  bundling in software projects, including commercial.
- Audio graph: `synth → masterGain → destination`. An FX chain (reverb /
  distortion / delay / …) is inserted before `masterGain` in a later step.

## Decisions on top of the handoff (confirmed by Sophie, 2026-10-29)

- **Reverb off by default**, with a planned **Settings → Audio FX** panel for
  reverb/distortion/delay/etc. The audio graph is built around an insertable FX
  chain for this.
- **Hosting:** public **GitHub Pages** (configured Pages-ready now; push at the
  end of Phase 1).
- Lone-petal role = solo (0 ¢) and leap-down effect = off — both match the
  handoff defaults.

## Build progress

- **Phase 1A · Check A — a piano note sounds.** ✅ (current)
- Next: hub-table inversion + settings model + `localStorage`, then the sound
  engine with channel rotation and the virtual hub (Check B).

## Research

The tuning research behind the Ensemble mode (findings, measured note table, and analysis code) is in [`research/`](research/README.md).

Live site: https://sophieg428.github.io/tunagon/
