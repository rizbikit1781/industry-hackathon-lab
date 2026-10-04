"use client";

import { useState } from "react";
import { POLICY, POLICY_ORDER } from "@/lib/colors";
import type { PolicyKey } from "@/lib/types";
import { useWidth } from "./useWidth";

export interface BarMetric {
  key: string;
  title: string;
  better: "higher" | "lower";
  values: Record<PolicyKey, number>;
  fmt: (v: number) => string;
}

const BAR = 18; // <= 24px
const GAP = 10;
const LABEL_W = 92;

/** One small panel: three horizontal bars (one per policy) from a shared zero baseline. */
export function PolicyBarPanel({ m }: { m: BarMetric }) {
  const [ref, w] = useWidth<HTMLDivElement>(280);
  const [hover, setHover] = useState<PolicyKey | null>(null);
  const max = Math.max(...POLICY_ORDER.map((p) => m.values[p]), 1e-9);
  const valueRoom = 56;
  const plotW = Math.max(40, w - LABEL_W - valueRoom);
  const h = POLICY_ORDER.length * (BAR + GAP) - GAP;
  const vals = POLICY_ORDER.map((p) => m.values[p]);
  const bestVal = m.better === "higher" ? Math.max(...vals) : Math.min(...vals);
  const isBest = (p: PolicyKey) => m.fmt(m.values[p]) === m.fmt(bestVal);

  return (
    <figure className="rounded-lg border border-line bg-surface px-4 py-3">
      <figcaption className="mb-3">
        <span className="block text-sm font-medium text-ink">{m.title}</span>
        <span className="block text-[11px] text-ink-3">{m.better === "higher" ? "Higher is better" : "Lower is better"}</span>
      </figcaption>
      <div ref={ref} className="relative">
        <svg width={w} height={h} role="img" aria-label={`${m.title}: ${POLICY_ORDER.map((p) => `${POLICY[p].label} ${m.fmt(m.values[p])}`).join(", ")}`}>
          {POLICY_ORDER.map((p, i) => {
            const y = i * (BAR + GAP);
            const bw = Math.max(2, (m.values[p] / max) * plotW);
            const r = Math.min(4, bw / 2);
            const x0 = LABEL_W;
            // square at baseline, 4px rounded data-end
            const d = `M${x0},${y} H${x0 + bw - r} Q${x0 + bw},${y} ${x0 + bw},${y + r} V${y + BAR - r} Q${x0 + bw},${y + BAR} ${x0 + bw - r},${y + BAR} H${x0} Z`;
            const dim = hover && hover !== p;
            return (
              <g
                key={p}
                tabIndex={0}
                onPointerEnter={() => setHover(p)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(p)}
                onBlur={() => setHover(null)}
                className="outline-none"
              >
                <rect x={0} y={y - GAP / 2} width={w} height={BAR + GAP} fill="transparent" />
                <text x={0} y={y + BAR / 2} dominantBaseline="central" fontSize={12} fill="var(--ink-2)">
                  {POLICY[p].short}
                </text>
                <path d={d} fill={POLICY[p].color} opacity={dim ? 0.45 : 1} />
                <text
                  x={x0 + bw + 6}
                  y={y + BAR / 2}
                  dominantBaseline="central"
                  fontSize={12}
                  fontWeight={isBest(p) ? 600 : 400}
                  fill={isBest(p) ? "var(--ink)" : "var(--ink-2)"}
                  className="tnum"
                >
                  {m.fmt(m.values[p])}
                </text>
              </g>
            );
          })}
          <line x1={LABEL_W} x2={LABEL_W} y1={-4} y2={h + 4} stroke="#383a40" strokeWidth={1} />
        </svg>
        {hover && (
          <div className="pointer-events-none absolute right-0 top-[-6px] rounded-md border border-line bg-surface-2 px-2 py-1 text-xs shadow-lg">
            <span className="font-semibold text-ink tnum">{m.fmt(m.values[hover])}</span>{" "}
            <span className="text-ink-3">{POLICY[hover].label}</span>
          </div>
        )}
      </div>
    </figure>
  );
}
