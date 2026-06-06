// Tiny dependency-free charts: SVG sparkline + CSS bars + a stat tile.

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border bg-white px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-xs text-gray-400">{hint}</div>}
    </div>
  );
}

/** SVG polyline over a numeric series; nulls are skipped. */
export function Sparkline({
  values,
  width = 140,
  height = 32,
  min = 0,
  max = 1,
}: {
  values: (number | null | undefined)[];
  width?: number;
  height?: number;
  min?: number;
  max?: number;
}) {
  const pts = values
    .map((v, i) => ({ v, i }))
    .filter((p) => p.v !== null && p.v !== undefined) as { v: number; i: number }[];
  if (pts.length === 0) {
    return <span className="text-xs text-gray-400">no data</span>;
  }
  const n = values.length;
  const span = max - min || 1;
  const x = (i: number) => (n <= 1 ? width / 2 : (i / (n - 1)) * (width - 4) + 2);
  const y = (v: number) => height - 2 - ((v - min) / span) * (height - 4);
  const d = pts.map((p) => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} role="img" aria-label="sparkline" className="overflow-visible">
      {pts.length > 1 && (
        <polyline points={d} fill="none" stroke="#6366f1" strokeWidth="1.5" />
      )}
      <circle cx={x(last.i)} cy={y(last.v)} r="2.5" fill="#6366f1" />
    </svg>
  );
}

/** Horizontal labelled bars; each value is 0..1 unless `max` given. */
export function Bars({
  items,
  max = 1,
}: {
  items: { label: string; value: number | null }[];
  max?: number;
}) {
  return (
    <div className="space-y-1">
      {items.map((it) => (
        <div key={it.label} className="flex items-center gap-2 text-xs">
          <span className="w-20 shrink-0 text-gray-500">{it.label}</span>
          <div className="h-3 flex-1 rounded bg-gray-100">
            <div
              className="h-3 rounded bg-brand"
              style={{ width: `${Math.max(0, Math.min(1, (it.value ?? 0) / max)) * 100}%` }}
            />
          </div>
          <span className="w-10 shrink-0 text-right tabular-nums">
            {it.value === null ? "—" : it.value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}
