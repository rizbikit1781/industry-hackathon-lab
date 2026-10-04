"use client";

import { useEffect, useMemo, useState } from "react";
import OpsMap, { type MapDepot, type MapRoute, type MapStop } from "./OpsMap";
import MapLegend from "./MapLegend";
import DailyLine from "./charts/DailyLine";
import { PolicyBarPanel, type BarMetric } from "./charts/PolicyBars";
import { Notice } from "./ui";
import { POLICY, POLICY_ORDER, crewColor, percentileWithin, tierFromPercentile } from "@/lib/colors";
import { dayLabel, num, pct } from "@/lib/format";
import type { PolicyKey, PolicyMetrics, ReplayDay, ReplaySummary } from "@/lib/types";

const pick = (s: ReplaySummary, f: (m: PolicyMetrics) => number) =>
  Object.fromEntries(POLICY_ORDER.map((p) => [p, f(s.policies[p].metrics)])) as Record<PolicyKey, number>;

export default function ReplayView({ summary }: { summary: ReplaySummary }) {
  const [policy, setPolicy] = useState<PolicyKey>("optimized");
  const [day, setDay] = useState(0);
  const [data, setData] = useState<ReplayDay | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedCrew, setSelectedCrew] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      fetch(`/api-internal/replay?policy=${policy}&day=${day}`, { signal: ac.signal, cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { error?: string }).error ?? `HTTP ${r.status}`);
          return r.json() as Promise<ReplayDay>;
        })
        .then((d) => {
          setData(d);
          setErr(null);
        })
        .catch((e) => {
          if (!ac.signal.aborted) setErr(e instanceof Error ? e.message : "failed to load");
        })
        .finally(() => !ac.signal.aborted && setLoading(false));
    }, 0);
    return () => {
      clearTimeout(t);
      ac.abort();
    };
  }, [policy, day]);

  const crewIds = useMemo(() => summary.crews.map((c) => c.id).sort(), [summary]);
  const routes: MapRoute[] = useMemo(
    () =>
      (data?.routes ?? []).map((r) => ({
        crew: r.crew,
        color: crewColor(r.crew, crewIds),
        coords: r.geometry && r.geometry.length > 1 ? r.geometry : r.path,
        roadGeometry: !!(r.geometry && r.geometry.length > 1),
      })),
    [data, crewIds],
  );
  const stops: MapStop[] = useMemo(() => {
    const ms = (data?.markers ?? []).filter((m) => m.lat != null && m.lon != null);
    const pctl = percentileWithin(ms, (m) => m.exposure, (m) => m.skill);
    return ms.map((m, i) => {
      const p = pctl.get(m) ?? 0.5;
      return {
        id: `${m.comm_code}-${m.skill}-${i}`,
        lon: m.lon,
        lat: m.lat,
        tier: m.high_risk ? "high" : tierFromPercentile(Math.min(p, 0.74)),
        planned: m.served_today > 0,
        title: `Community ${m.name ?? m.comm_code} · ${m.skill === "bylaw" ? "sidewalk (bylaw)" : "roads / pathway"}`,
        detail: `${m.open} open · ${m.served_today} served this day`,
        reason: m.reason,
        crew: null,
      };
    });
  }, [data]);
  const depots: MapDepot[] = useMemo(() => {
    const m = new Map<string, MapDepot>();
    for (const c of summary.crews) {
      const k = `${c.depot_lon.toFixed(5)},${c.depot_lat.toFixed(5)}`;
      const d = m.get(k);
      if (d) d.label += `, ${c.id}`;
      else m.set(k, { lon: c.depot_lon, lat: c.depot_lat, label: c.id });
    }
    return [...m.values()];
  }, [summary]);

  const M = (p: PolicyKey) => summary.policies[p].metrics;
  const sel = M(policy);
  const fifo = M("fifo");
  const info = summary.policies[policy].daily[day];
  const replansToday = summary.policies[policy].replans.filter((r) => r.day === summary.days[day]);
  const roadGeometry = routes.some((r) => r.roadGeometry);

  const bars: BarMetric[] = [
    { key: "hr48", title: "High-risk tickets served within 48 h", better: "higher", values: pick(summary, (m) => m.high_risk_within_48h), fmt: (v) => pct(v, 1) },
    { key: "all48", title: "All tickets served within 48 h", better: "higher", values: pick(summary, (m) => m.all_within_48h), fmt: (v) => pct(v, 1) },
    { key: "hrw", title: "High-risk tickets served in the week", better: "higher", values: pick(summary, (m) => m.high_risk_served), fmt: (v) => pct(v, 1) },
    { key: "lrw", title: "Low-risk tickets served in the week", better: "higher", values: pick(summary, (m) => m.low_risk_served), fmt: (v) => pct(v, 1) },
    { key: "km", title: "Total km driven (7 days)", better: "lower", values: pick(summary, (m) => m.total_km), fmt: (v) => num(v) },
    { key: "kmt", title: "km per ticket", better: "lower", values: pick(summary, (m) => m.km_per_ticket), fmt: (v) => num(v, 2) },
    { key: "med", title: "Median days to service", better: "lower", values: pick(summary, (m) => m.median_days_to_service), fmt: (v) => num(v) },
    { key: "p90", title: "p90 days to service", better: "lower", values: pick(summary, (m) => m.p90_days_to_service), fmt: (v) => num(v) },
  ];

  const worse = bars.filter((b) => {
    const a = b.values.optimized;
    const f = b.values.fifo;
    return b.better === "higher" ? a < f : a > f;
  });

  const rows: { label: string; f: (m: PolicyMetrics) => string }[] = [
    { label: "High-risk served within 48 h", f: (m) => pct(m.high_risk_within_48h, 1) },
    { label: "All tickets served within 48 h", f: (m) => pct(m.all_within_48h, 1) },
    { label: "High-risk served in the week", f: (m) => pct(m.high_risk_served, 1) },
    { label: "Low-risk served in the week", f: (m) => pct(m.low_risk_served, 1) },
    { label: "p90 days to service", f: (m) => num(m.p90_days_to_service) },
    { label: "p90 days, high-risk", f: (m) => num(m.p90_days_high_risk) },
    { label: "Median days to service", f: (m) => num(m.median_days_to_service) },
    { label: "Tickets served (incl. warm start)", f: (m) => num(m.tickets_served) },
    { label: "Backlog at end of week", f: (m) => num(m.backlog_end) },
    { label: "Total km driven", f: (m) => num(m.total_km) },
    { label: "km per ticket", f: (m) => num(m.km_per_ticket, 2) },
    { label: "Crew stops", f: (m) => num(m.stops) },
    { label: "Jobs moved per replan", f: (m) => (m.jobs_moved_per_replan == null ? "n/a" : num(m.jobs_moved_per_replan)) },
  ];

  const hrSeries = Object.fromEntries(POLICY_ORDER.map((p) => [p, summary.policies[p].daily.map((d) => d.high_risk_served)])) as Record<PolicyKey, number[]>;
  const kmSeries = Object.fromEntries(POLICY_ORDER.map((p) => [p, summary.policies[p].daily.map((d) => d.km)])) as Record<PolicyKey, number[]>;
  const cap = summary.capacity;

  return (
    <div className="cs-scroll min-h-0 flex-1 overflow-y-auto">
      {/* controls: one row above everything they scope */}
      <div className="sticky top-0 z-20 flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line bg-surface/95 px-4 py-3 backdrop-blur">
        <div className="mr-auto">
          <h1 className="text-base font-semibold tracking-tight">Storm-week replay</h1>
          <p className="text-xs text-ink-3">
            Real Calgary 311 snow &amp; ice tickets, {dayLabel(summary.days[0])} – {dayLabel(summary.days[summary.days.length - 1])}, 2025 · same crews &amp; capacity for every policy
          </p>
        </div>
        <fieldset className="flex items-center gap-2">
          <legend className="sr-only">Policy</legend>
          <span className="text-xs text-ink-3" aria-hidden="true">Policy</span>
          <div className="flex rounded-lg border border-line bg-bg p-0.5">
            {POLICY_ORDER.map((p) => (
              <label
                key={p}
                className={`flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-sm has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
                  policy === p ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink-2"
                }`}
              >
                <input type="radio" name="policy" value={p} checked={policy === p} onChange={() => setPolicy(p)} className="sr-only" />
                <span className="h-2 w-2 rounded-full" style={{ background: POLICY[p].color }} aria-hidden="true" />
                {POLICY[p].label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setDay((d) => Math.max(0, d - 1))} disabled={day === 0} className="rounded-md border border-line px-2 py-1 text-sm text-ink-2 hover:bg-surface-2 disabled:opacity-40" aria-label="Previous day">
            ←
          </button>
          <label className="flex items-center gap-3">
            <span className="sr-only">Day</span>
            <input
              type="range"
              min={0}
              max={summary.days.length - 1}
              step={1}
              value={day}
              onChange={(e) => setDay(Number(e.target.value))}
              className="cs-range w-44"
              aria-valuetext={`Day ${day + 1}, ${dayLabel(summary.days[day])}`}
            />
            <span className="w-32 text-sm tnum">
              <span className="text-ink-3">Day {day + 1}</span> <span className="font-medium">{dayLabel(summary.days[day])}</span>
            </span>
          </label>
          <button type="button" onClick={() => setDay((d) => Math.min(summary.days.length - 1, d + 1))} disabled={day === summary.days.length - 1} className="rounded-md border border-line px-2 py-1 text-sm text-ink-2 hover:bg-surface-2 disabled:opacity-40" aria-label="Next day">
            →
          </button>
        </div>
      </div>

      {/* map + day panel */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] xl:grid-cols-[1fr_460px]">
        <div className="relative h-[calc(100vh-7.5rem)] min-h-[480px]">
          <OpsMap
            routes={routes}
            stops={stops}
            depots={depots}
            selectedCrew={selectedCrew}
            onSelectCrew={setSelectedCrew}
            ariaLabel={`Map of ${POLICY[policy].label} crew routes on ${dayLabel(summary.days[day])}`}
          />
          <div className="pointer-events-none absolute left-3 top-3">
            <MapLegend roadGeometry={roadGeometry} />
          </div>
          {selectedCrew && (
            <button type="button" onClick={() => setSelectedCrew(null)} className="absolute bottom-8 left-3 rounded-md border border-line bg-surface/95 px-3 py-1.5 text-sm text-ink-2 hover:text-ink">
              Showing {selectedCrew} only · show all
            </button>
          )}
          {loading && <div className="absolute bottom-8 right-3 rounded-md bg-surface/90 px-2 py-1 text-xs text-ink-3">Loading day…</div>}
          {err && (
            <div className="absolute inset-x-3 bottom-8">
              <Notice tone="error" title="Could not load this day">{err}</Notice>
            </div>
          )}
        </div>

        <aside className="flex flex-col gap-5 border-l border-line bg-surface px-5 py-5" aria-label="Day summary">
          <div>
            <div className="text-xs text-ink-3">High-risk tickets served within 48 h, whole week</div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="text-5xl font-semibold tracking-tight">{pct(sel.high_risk_within_48h, 1)}</span>
              {policy !== "fifo" && (
                <span className={`text-sm ${sel.high_risk_within_48h >= fifo.high_risk_within_48h ? "text-emerald-400" : "text-amber-300"}`}>
                  {sel.high_risk_within_48h >= fifo.high_risk_within_48h ? "+" : "−"}
                  {Math.abs((sel.high_risk_within_48h - fifo.high_risk_within_48h) * 100).toFixed(1)} pts vs FIFO
                </span>
              )}
            </div>
            <div className="mt-1 text-sm text-ink-3">
              {POLICY[policy].label}
              {policy !== "fifo" && <> · FIFO: {pct(fifo.high_risk_within_48h, 1)}</>}
            </div>
          </div>

          <div>
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-3">{dayLabel(info.day)}, {POLICY[policy].short}</h2>
            <dl className="grid grid-cols-3 gap-x-3 gap-y-3">
              <DayStat label="Tickets served" value={num(info.served)} />
              <DayStat label="High-risk served" value={num(info.high_risk_served)} />
              <DayStat label="Crew stops" value={num(info.stops)} />
              <DayStat label="km driven" value={num(info.km)} />
              <DayStat label="Open at start" value={num(info.open_morning)} />
              <DayStat label="New arrivals" value={num(info.arrivals)} />
              <DayStat label="Crews active" value={`${info.crews_active} / ${summary.crews.length}`} />
              <DayStat label="Solve time" value={`${info.solve_s.toFixed(1)} s`} />
            </dl>
            {replansToday.map((r) => (
              <div key={r.kind} className="mt-3 rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-3 py-2 text-xs text-ink-2">
                <span className="font-medium text-ink">{r.kind === "surge" ? `Mid-day surge (${num(r.n_new)} real arrivals)` : `${r.crews_out?.length ?? 0} crews out (${r.crews_out?.join(", ")})`}</span>
                : {r.jobs_moved} of {r.jobs_before} planned stops moved, re-solved in {r.replan_s.toFixed(1)} s. High-risk tickets planned {r.high_risk_planned_before} → {r.high_risk_planned_after}.
              </div>
            ))}
          </div>

          <DailyLine title="High-risk tickets served per day" days={summary.days} series={hrSeries} selectedDay={day} onSelectDay={setDay} height={190} />
          <DailyLine title="Km driven per day" days={summary.days} series={kmSeries} selectedDay={day} onSelectDay={setDay} height={170} fmt={(v) => num(v)} />
        </aside>
      </div>

      {/* comparison */}
      <section className="border-t border-line px-6 py-8" aria-labelledby="compare">
        <div className="mx-auto max-w-[1400px]">
          <h2 id="compare" className="text-lg font-semibold tracking-tight">Compare policies</h2>
          <p className="mt-1 max-w-3xl text-sm text-ink-3">
            Same {cap.bylaw.crews} bylaw officers × {cap.bylaw.tickets_per_crew} and {cap.roads.crews} Roads crews × {cap.roads.tickets_per_crew} tickets a day (calibrated to the City&apos;s median real daily closures). Only the dispatch rule changes. High-risk = top quartile of exposure within each crew type, fixed before any policy runs.
          </p>
          <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {bars.map((b) => (
              <PolicyBarPanel key={b.key} m={b} />
            ))}
          </div>

          {worse.length > 0 && (
            <div className="mt-4 rounded-lg border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm text-ink-2">
              <span className="font-medium text-amber-200">Where SnowTech is worse than FIFO: </span>
              {worse.map((b, i) => (
                <span key={b.key}>
                  {i > 0 && "; "}
                  {b.title.toLowerCase()} ({b.fmt(b.values.optimized)} vs {b.fmt(b.values.fifo)})
                </span>
              ))}
              . That is the cost of triage when crew capacity is about half of demand: FIFO bounds the oldest wait, SnowTech does not.
            </div>
          )}

          <div className="mt-6 overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-sm">
              <caption className="sr-only">All replay metrics by policy</caption>
              <thead className="bg-surface text-left text-xs text-ink-3">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Metric (Nov 25 – Dec 1)</th>
                  {POLICY_ORDER.map((p) => (
                    <th key={p} scope="col" className="px-4 py-2.5 text-right font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full" style={{ background: POLICY[p].color }} aria-hidden="true" />
                        {POLICY[p].label}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={r.label} className="hover:bg-surface/60">
                    <th scope="row" className="px-4 py-2 text-left font-normal text-ink-2">{r.label}</th>
                    {POLICY_ORDER.map((p) => (
                      <td key={p} className="px-4 py-2 text-right tnum text-ink">{r.f(M(p))}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-ink-3">
            Source: <code className="font-mono">data/results.json</code> (output of <code className="font-mono">scripts/run_sim.py</code>), file updated {new Date(summary.generated_mtime).toLocaleString("en-CA")}. A ticket&apos;s closure date is not the moment the ice was cleared; FIFO is our model of a no-triage queue, not the City&apos;s real dispatch.
          </p>
        </div>
      </section>
    </div>
  );
}

function DayStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="text-lg font-semibold tnum">{value}</dd>
    </div>
  );
}
