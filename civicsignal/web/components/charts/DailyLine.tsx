"use client";

import { useState } from "react";
import { POLICY, POLICY_ORDER } from "@/lib/colors";
import { dayLabel } from "@/lib/format";
import type { PolicyKey } from "@/lib/types";
import { useWidth } from "./useWidth";

interface Props {
  title: string;
  days: string[];
  series: Record<PolicyKey, number[]>;
  selectedDay: number;
  onSelectDay?: (i: number) => void;
  fmt?: (v: number) => string;
  height?: number;
}

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/** Multi-series line chart, one shared y axis, crosshair + all-series tooltip. */
export default function DailyLine({ title, days, series, selectedDay, onSelectDay, fmt = (v) => v.toLocaleString("en-CA"), height = 200 }: Props) {
  const [ref, w] = useWidth<HTMLDivElement>(400);
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 44, r: 22, t: 10, b: 24 };
  const pw = w - m.l - m.r;
  const ph = height - m.t - m.b;
  const ymax = niceMax(Math.max(...POLICY_ORDER.flatMap((p) => series[p])));
  const x = (i: number) => m.l + (days.length > 1 ? (i / (days.length - 1)) * pw : pw / 2);
  const y = (v: number) => m.t + ph - (v / ymax) * ph;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * ymax);
  const idx = hover ?? null;

  const pick = (clientX: number, rect: DOMRect) => {
    const px = clientX - rect.left - m.l;
    return Math.max(0, Math.min(days.length - 1, Math.round((px / pw) * (days.length - 1))));
  };

  return (
    <figure>
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-sm font-medium text-ink">{title}</span>
        <span className="flex gap-3 text-[11px] text-ink-2" aria-hidden="true">
          {POLICY_ORDER.map((p) => (
            <span key={p} className="flex items-center gap-1.5">
              <span className="h-0.5 w-3.5 rounded" style={{ background: POLICY[p].color }} />
              {POLICY[p].short}
            </span>
          ))}
        </span>
      </figcaption>
      <div ref={ref} className="relative">
        <svg
          width={w}
          height={height}
          role="img"
          aria-label={`${title}. ${POLICY_ORDER.map((p) => `${POLICY[p].label}: ${series[p].map(fmt).join(", ")}`).join(". ")}`}
          onPointerMove={(e) => setHover(pick(e.clientX, e.currentTarget.getBoundingClientRect()))}
          onPointerLeave={() => setHover(null)}
          onClick={(e) => onSelectDay?.(pick(e.clientX, e.currentTarget.getBoundingClientRect()))}
          className={onSelectDay ? "cursor-pointer" : undefined}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={w - m.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? "#383a40" : "#222429"} strokeWidth={1} />
              <text x={m.l - 8} y={y(t)} textAnchor="end" dominantBaseline="central" fontSize={11} fill="var(--ink-3)" className="tnum">
                {fmt(t)}
              </text>
            </g>
          ))}
          {days.map((d, i) => (
            <text key={d} x={x(i)} y={height - 6} textAnchor={i === days.length - 1 ? "end" : "middle"} fontSize={11} fill={i === selectedDay ? "var(--ink)" : "var(--ink-3)"} fontWeight={i === selectedDay ? 600 : 400}>
              {new Date(`${d}T12:00:00`).toLocaleDateString("en-CA", { month: "short", day: "numeric" })}
            </text>
          ))}
          {/* selected day band */}
          <rect x={x(selectedDay) - 10} y={m.t} width={20} height={ph} fill="#3987e5" opacity={0.08} rx={3} />
          {POLICY_ORDER.map((p) => (
            <polyline
              key={p}
              fill="none"
              stroke={POLICY[p].color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              points={series[p].map((v, i) => `${x(i)},${y(v)}`).join(" ")}
            />
          ))}
          {idx != null && <line x1={x(idx)} x2={x(idx)} y1={m.t} y2={m.t + ph} stroke="#6b6d75" strokeWidth={1} />}
          {POLICY_ORDER.map((p) => {
            const i = idx ?? selectedDay;
            return <circle key={p} cx={x(i)} cy={y(series[p][i])} r={4} fill={POLICY[p].color} stroke="var(--surface)" strokeWidth={2} />;
          })}
        </svg>
        {idx != null && (
          <div
            className="pointer-events-none absolute top-0 z-10 min-w-[170px] rounded-md border border-line bg-surface-2 px-2.5 py-2 text-xs shadow-xl shadow-black/40"
            style={{ left: Math.min(Math.max(x(idx) + 12, 0), w - 180) }}
          >
            <div className="mb-1 text-ink-3">{dayLabel(days[idx])}</div>
            {POLICY_ORDER.map((p) => (
              <div key={p} className="flex items-center gap-2">
                <span className="h-0.5 w-3 rounded" style={{ background: POLICY[p].color }} />
                <span className="font-semibold text-ink tnum">{fmt(series[p][idx])}</span>
                <span className="text-ink-3">{POLICY[p].short}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
}
