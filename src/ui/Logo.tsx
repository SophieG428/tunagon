// Tuneagon logo — a petal-shaped hexagon (flat top & bottom, vertices at 3 and 9
// o'clock, exactly like the real petals) split into its six triangular keys, with
// one key "lit" in the blue accent. Brand purple matches the favicon (#863bff).

const V: [number, number][] = [
  [96, 50], // 3 o'clock vertex
  [73, 89.84],
  [27, 89.84],
  [4, 50], // 9 o'clock vertex
  [27, 10.16],
  [73, 10.16],
];
const CX = 50;
const CY = 50;
const FILLS = [0.9, 0.62, 0.78, 0.5, 0.7, 0.58]; // faceted purple tints
const LIT_KEY = 5; // one triangle shown in the blue accent

export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg
      className="brand-logo"
      width={size}
      height={size}
      viewBox="0 0 100 100"
      role="img"
      aria-label="Tuneagon logo"
    >
      {V.map((_, i) => {
        const b = V[(i + 1) % 6];
        const a = V[i];
        const lit = i === LIT_KEY;
        return (
          <path
            key={i}
            d={`M${CX} ${CY} L${a[0]} ${a[1]} L${b[0]} ${b[1]} Z`}
            fill={lit ? "var(--logo-accent, #47bfff)" : "var(--logo, #863bff)"}
            fillOpacity={lit ? 0.95 : FILLS[i]}
          />
        );
      })}
      {/* subtle dividers between the six keys */}
      {V.map((p, i) => (
        <line
          key={`s${i}`}
          x1={CX}
          y1={CY}
          x2={p[0]}
          y2={p[1]}
          stroke="#fff"
          strokeOpacity="0.18"
          strokeWidth="1.5"
        />
      ))}
      <polygon
        points={V.map((p) => p.join(",")).join(" ")}
        fill="none"
        stroke="var(--logo, #863bff)"
        strokeWidth="4"
        strokeLinejoin="round"
      />
    </svg>
  );
}
