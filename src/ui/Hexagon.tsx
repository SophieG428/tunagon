// The petal hexagon: flat sides top and bottom, vertices at 3 and 9 o'clock.
// Six triangles numbered 0..5 counter-clockwise from the upper-right triangle
// (handoff 5.3). Triangle t shows physical key `physicalKey(t, layout)`, lights
// while that key is down, with brightness following pressure.
//
// When `onKeyClick` is supplied the triangles become clickable (used by the
// per-key editor); `selectedKey` outlines one physical key.

import type { PetalConfig } from "../state/config";
import { getLive } from "../state/liveState";
import { noteName } from "../util/notes";

function physicalKey(t: number, layout: PetalConfig["layout"]): number {
  const base = layout.mirrored ? (6 - t) % 6 : t;
  return (base + layout.rotation) % 6;
}

interface HexagonProps {
  cfg: PetalConfig;
  size?: number;
  onKeyClick?: (physicalKey: number) => void;
  selectedKey?: number | null;
}

export function Hexagon({ cfg, size = 150, onKeyClick, selectedKey = null }: HexagonProps) {
  const live = getLive(cfg.id);
  const cx = size / 2;
  const cy = size / 2;
  const r = (size / 2) * 0.94;
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const vx = (deg: number) => cx + r * Math.cos(rad(deg));
  const vy = (deg: number) => cy - r * Math.sin(rad(deg)); // screen y is down

  const triangles = [];
  for (let t = 0; t < 6; t++) {
    const k = physicalKey(t, cfg.layout);
    const note = cfg.keys[k];
    const down = live.keysDown[k];
    const silent = note == null;
    const level = down ? Math.max(0.2, live.pressure / 127) : 0;
    const a0 = 60 * t;
    const a1 = 60 * (t + 1);
    const mid = 60 * t + 30;
    triangles.push({
      t,
      k,
      note,
      down,
      silent,
      level,
      selected: selectedKey === k,
      points: `${cx},${cy} ${vx(a0)},${vy(a0)} ${vx(a1)},${vy(a1)}`,
      lx: cx + r * 0.6 * Math.cos(rad(mid)),
      ly: cy - r * 0.6 * Math.sin(rad(mid)),
    });
  }

  const interactive = !!onKeyClick;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={`hexagon${interactive ? " interactive" : ""}`}
      aria-hidden="true"
    >
      {triangles.map((tr) => {
        const fill = tr.down
          ? `rgba(170, 59, 255, ${0.25 + 0.7 * tr.level})`
          : tr.selected
            ? "var(--accent-bg)"
            : tr.silent
              ? "rgba(128, 128, 128, 0.06)"
              : "var(--code-bg)";
        return (
          <g key={tr.t} onClick={interactive ? () => onKeyClick?.(tr.k) : undefined}>
            <polygon
              points={tr.points}
              fill={fill}
              stroke={tr.selected ? "var(--accent)" : "var(--border)"}
              strokeWidth={tr.selected ? 2.5 : 1.5}
            />
            <text
              x={tr.lx}
              y={tr.ly}
              textAnchor="middle"
              dominantBaseline="central"
              className={`hex-label${tr.silent ? " silent" : ""}${tr.down ? " lit" : ""}`}
            >
              {tr.note == null ? "—" : noteName(tr.note)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
