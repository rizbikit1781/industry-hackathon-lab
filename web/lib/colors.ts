import type { PolicyKey } from "./types";

/** Policy series colours: dataviz reference palette, dark steps (slots 2, 1, 3), validated
 * against the app surface #111214 (all 3 pass band/chroma/CVD/contrast checks). */
export const POLICY: Record<PolicyKey, { label: string; short: string; color: string }> = {
  fifo: { label: "FIFO (oldest first)", short: "FIFO", color: "#d95926" },
  optimized: { label: "CivicSignal", short: "CivicSignal", color: "#3987e5" },
  optimized_disruption: { label: "CivicSignal + disruption", short: "+ disruption", color: "#199e70" },
};
export const POLICY_ORDER: PolicyKey[] = ["fifo", "optimized", "optimized_disruption"];

/** Ordinal risk tiers for stops (top quartile of exposure within crew type = high). */
export const RISK = {
  high: { label: "High exposure (top 25%)", color: "#f06262" },
  mid: { label: "Medium", color: "#d9a03a" },
  low: { label: "Low (bottom 25%)", color: "#6b7686" },
} as const;
export type RiskTier = keyof typeof RISK;

export const VOICE_COLOR = "#7dd3fc";

/** One colour per crew for route lines. 17 crews is past any categorical palette, so crews are
 * also identified by ID in the list, on hover, and by click-to-isolate on the map. */
export function crewColor(id: string, allIds: string[]): string {
  const i = Math.max(0, allIds.indexOf(id));
  const n = Math.max(allIds.length, 1);
  // stride through the hue wheel so neighbouring crew IDs get distant hues
  // Hues are kept in 75..335 deg so routes never read as the red/amber risk tiers on the stops.
  const stride = 7;
  const hue = 75 + (((i * stride) % n) / n) * 260;
  return `hsl(${hue.toFixed(0)} 70% 64%)`;
}

export function tierFromPercentile(p: number): RiskTier {
  return p >= 0.75 ? "high" : p <= 0.25 ? "low" : "mid";
}

/** Percentile rank of each value within its group (e.g. exposure within crew type). */
export function percentileWithin<T>(items: T[], value: (t: T) => number, group: (t: T) => string): Map<T, number> {
  const by = new Map<string, T[]>();
  for (const it of items) {
    const g = group(it);
    if (!by.has(g)) by.set(g, []);
    by.get(g)!.push(it);
  }
  const out = new Map<T, number>();
  for (const arr of by.values()) {
    const sorted = [...arr].sort((a, b) => value(a) - value(b));
    sorted.forEach((it, i) => out.set(it, arr.length > 1 ? i / (arr.length - 1) : 1));
  }
  return out;
}
