export const pct = (x: number | null | undefined, d = 0) =>
  x == null || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(d)}%`;
export const num = (x: number | null | undefined, d = 0) =>
  x == null || Number.isNaN(x) ? "—" : x.toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d });
export const hm = (min: number | null | undefined) => {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
};
export const dayLabel = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("en-CA", { weekday: "short", month: "short", day: "numeric" });
