"use client";

import Script from "next/script";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import OpsMap, { type MapDepot, type MapRoute, type MapStop, type MapVoice } from "./OpsMap";
import MapLegend from "./MapLegend";
import { Kbd, Notice, Section, Stat } from "./ui";
import { crewColor, percentileWithin, tierFromPercentile } from "@/lib/colors";
import { dayLabel, hm, num, pct } from "@/lib/format";
import type { Crew, DisruptionResult, LiveJob, LiveMetrics, LivePlan } from "@/lib/types";

const POLL_MS = 2500;

type Toast = { id: number; title: string; body: string };
type Action = "out" | "restore" | "surge";
type ReplanEvent = { action: Action; at: Date; result: DisruptionResult };

const SERVICE_SHORT: Record<string, string> = {
  "Bylaw - Snow and Ice on Sidewalk": "Sidewalk",
  "Roads - Snow and Ice Control": "Road",
  "Roads - Pathway Snow and Ice Concerns": "Pathway",
};
const short = (s: string) => SERVICE_SHORT[s] ?? s;

export default function LiveConsole({ agentId, allCrews }: { agentId: string | null; allCrews: Crew[] }) {
  const [plan, setPlan] = useState<LivePlan | null>(null);
  const [metrics, setMetrics] = useState<LiveMetrics["live"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [selectedCrew, setSelectedCrew] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ lon: number; lat: number; key: string } | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [busy, setBusy] = useState<Action | null>(null);
  const [replans, setReplans] = useState<ReplanEvent[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);

  const planText = useRef<string>("");
  const seenVoice = useRef<Set<string> | null>(null);
  const inFlight = useRef(false);
  const toastId = useRef(0);

  const pushToast = useCallback((title: string, body: string) => {
    const id = ++toastId.current;
    setToasts((t) => [...t.slice(-2), { id, title, body }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
  }, []);

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const [pr, mr] = await Promise.all([
        fetch("/api/plan", { cache: "no-store", signal: AbortSignal.timeout(8000) }),
        fetch("/api/metrics", { cache: "no-store", signal: AbortSignal.timeout(8000) }),
      ]);
      if (!pr.ok) throw new Error(`GET /plan returned ${pr.status}`);
      const text = await pr.text();
      if (text !== planText.current) {
        planText.current = text;
        const p = JSON.parse(text) as LivePlan;
        setPlan(p);
        const ids = new Set(p.voice_jobs);
        if (seenVoice.current) {
          for (const id of p.voice_jobs) {
            if (!seenVoice.current.has(id)) {
              const j = p.jobs.find((x) => x.job_id === id);
              pushToast(
                `New voice report ${id}`,
                j
                  ? `${short(j.service_name)}${j.crew ? `, assigned to ${j.crew}` : ""}${j.reason ? `. ${j.reason}` : ""}`
                  : "Added to today's plan",
              );
              if (j) setFocus({ lon: j.lon, lat: j.lat, key: id });
              if (j?.crew) setSelectedCrew(j.crew);
            }
          }
        }
        seenVoice.current = ids;
      }
      if (mr.ok) setMetrics(((await mr.json()) as LiveMetrics).live);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      inFlight.current = false;
    }
  }, [pushToast]);

  useEffect(() => {
    const first = setTimeout(poll, 0);
    const t = setInterval(poll, POLL_MS);
    const c = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearTimeout(first);
      clearInterval(t);
      clearInterval(c);
    };
  }, [poll]);

  const disrupt = async (action: Action) => {
    setBusy(action);
    setActionError(null);
    const body = action === "out" ? { crews_out: 3 } : action === "restore" ? { crews_out: 0 } : { surge: true };
    try {
      const r = await fetch("/api-internal/disruption", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof j?.detail === "string" ? j.detail : `HTTP ${r.status}`);
      setReplans((x) => [{ action, at: new Date(), result: j as DisruptionResult }, ...x].slice(0, 5));
      planText.current = "";
      await poll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(null);
    }
  };

  // ---------------------------------------------------------------- derived
  const crewIds = useMemo(() => {
    const ids = new Set<string>(allCrews.map((c) => c.id));
    plan?.crews.forEach((c) => ids.add(c.id));
    return [...ids].sort();
  }, [allCrews, plan]);

  const crewMeta = useMemo(() => {
    const m = new Map<string, Crew>();
    allCrews.forEach((c) => m.set(c.id, c));
    plan?.crews.forEach((c) => m.set(c.id, c));
    return m;
  }, [allCrews, plan]);

  const routes: MapRoute[] = useMemo(
    () =>
      (plan?.routes ?? []).map((r) => ({
        crew: r.crew,
        color: crewColor(r.crew, crewIds),
        coords: r.geometry && r.geometry.length > 1 ? r.geometry : r.path,
        roadGeometry: !!(r.geometry && r.geometry.length > 1),
      })),
    [plan, crewIds],
  );
  const roadGeometry = routes.some((r) => r.roadGeometry);

  const { stops, voice, voiceJobs } = useMemo(() => {
    const jobs = plan?.jobs ?? [];
    const pctl = percentileWithin(jobs, (j) => j.exposure, (j) => j.skill);
    const stops: MapStop[] = [];
    const voice: MapVoice[] = [];
    const voiceJobs: LiveJob[] = [];
    for (const j of jobs) {
      if (j.lat == null || j.lon == null) continue;
      if (j.job_id.startsWith("V")) {
        voice.push({ id: j.job_id, lon: j.lon, lat: j.lat, reason: j.reason, crew: j.crew });
        voiceJobs.push(j);
        continue;
      }
      const p = pctl.get(j) ?? 0.5;
      stops.push({
        id: j.job_id,
        lon: j.lon,
        lat: j.lat,
        tier: tierFromPercentile(p),
        planned: !!j.crew,
        title: `${short(j.service_name)} · community ${j.comm_code ?? "?"}`,
        detail: `${j.n_tickets} ticket${j.n_tickets === 1 ? "" : "s"} · exposure pct ${Math.round(p * 100)} · ${
          j.crew ? `crew ${j.crew}, ETA +${hm(j.eta_min)} into shift` : "not in today's plan"
        }`,
        reason: j.reason,
        crew: j.crew,
      });
    }
    voiceJobs.sort((a, b) => b.job_id.localeCompare(a.job_id));
    return { stops, voice, voiceJobs };
  }, [plan]);

  const depots: MapDepot[] = useMemo(() => {
    const m = new Map<string, MapDepot>();
    for (const c of crewMeta.values()) {
      const k = `${c.depot_lon.toFixed(5)},${c.depot_lat.toFixed(5)}`;
      const d = m.get(k);
      if (d) d.label += `, ${c.id}`;
      else m.set(k, { lon: c.depot_lon, lat: c.depot_lat, label: `Depot: ${c.id}` });
    }
    return [...m.values()];
  }, [crewMeta]);

  const routeBy = useMemo(() => new Map((plan?.routes ?? []).map((r) => [r.crew, r])), [plan]);
  const ticketsBy = useMemo(() => {
    const m = new Map<string, number>();
    plan?.jobs.forEach((j) => j.crew && m.set(j.crew, (m.get(j.crew) ?? 0) + j.n_tickets));
    return m;
  }, [plan]);
  const stopsPlanned = useMemo(() => (plan?.routes ?? []).reduce((s, r) => s + r.stops.length, 0), [plan]);
  const activeIds = new Set(plan?.crews.map((c) => c.id) ?? []);
  const lastReplan = replans[0];
  const hrOpen = lastReplan?.result.high_risk_open;

  const ago = updatedAt ? Math.max(0, Math.round((now - updatedAt) / 1000)) : null;

  return (
    <div className="flex min-h-0 flex-1">
      {/* ---------------------------------------------------------------- side panel */}
      <aside
        aria-label="Operations panel"
        className="cs-scroll flex w-[380px] shrink-0 flex-col overflow-y-auto border-r border-line bg-surface xl:w-[420px]"
      >
        <div className="border-b border-line px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-base font-semibold tracking-tight">Live dispatch plan</h1>
            <span className="flex items-center gap-1.5 text-xs text-ink-3" aria-live="polite">
              <span
                className={`inline-block h-2 w-2 rounded-full ${error ? "bg-red-500" : plan ? "cs-live-dot bg-emerald-500" : "bg-zinc-500"}`}
                aria-hidden="true"
              />
              {error ? "Offline" : ago == null ? "Connecting…" : ago <= 3 ? "Live" : `Updated ${ago}s ago`}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-ink-3">
            {plan ? (
              <>
                Replay morning {dayLabel(plan.day)} · real open 311 queue · polls every {POLL_MS / 1000}s
              </>
            ) : (
              "Calgary 311 snow & ice, today's crew plan"
            )}
          </p>
        </div>

        {error && !plan && (
          <div className="px-4 pt-4">
            <Notice tone="error" title="API not reachable. Start uvicorn.">
              <div className="space-y-1.5">
                <div>{error}</div>
                <div>
                  From <Kbd>civicsignal/</Kbd>: <Kbd>.venv/bin/uvicorn civicsignal.api:app --port 8000</Kbd>
                </div>
              </div>
            </Notice>
          </div>
        )}
        {error && plan && (
          <div className="px-4 pt-4">
            <Notice tone="warn" title="Lost connection to the API">
              Showing the last plan received. Retrying every {POLL_MS / 1000}s. ({error})
            </Notice>
          </div>
        )}

        <Section title="Today's plan" id="kpis">
          <div className="grid grid-cols-2 gap-2">
            <Stat
              label="High-risk tickets planned"
              value={metrics ? num(metrics.high_risk_planned) : "—"}
              sub={hrOpen ? `${pct((metrics?.high_risk_planned ?? 0) / hrOpen)} of ${num(hrOpen)} open` : "top-quartile exposure"}
            />
            <Stat
              label="Stops planned"
              value={plan ? num(stopsPlanned) : "—"}
              sub={metrics ? `${num(metrics.tickets_planned_today)} tickets of ${num(metrics.open_tickets)} open` : undefined}
            />
            <Stat label="Distance" value={plan ? <>{num(plan.km, 0)} <span className="text-base font-normal text-ink-3">km</span></> : "—"} sub={roadGeometry ? "on the road network" : plan ? "straight-line legs shown" : undefined} />
            <Stat
              label="Crews active"
              value={plan ? <>{plan.crews.length}<span className="text-base font-normal text-ink-3"> / {crewIds.length}</span></> : "—"}
              sub={plan ? `${plan.crews.filter((c) => c.skill === "bylaw").length} bylaw · ${plan.crews.filter((c) => c.skill === "roads").length} roads` : undefined}
            />
          </div>
        </Section>

        <Section title="Simulate a disruption" id="disrupt">
          <div className="grid grid-cols-3 gap-2" role="group" aria-label="Disruption scenarios">
            <ActionButton onClick={() => disrupt("out")} busy={busy === "out"} disabled={!!busy || !plan} label="3 crews out" hint="sick calls" />
            <ActionButton onClick={() => disrupt("restore")} busy={busy === "restore"} disabled={!!busy || !plan} label="Restore crews" hint="all back" />
            <ActionButton onClick={() => disrupt("surge")} busy={busy === "surge"} disabled={!!busy || !plan} label="Surge" hint="next day's real 311" />
          </div>
          {busy && <p className="mt-2 text-xs text-ink-3" aria-live="polite">Re-solving with OR-Tools…</p>}
          {actionError && (
            <div className="mt-2">
              <Notice tone="error" title="Replan failed">{actionError}</Notice>
            </div>
          )}
          {lastReplan && <ReplanCard ev={lastReplan} />}
        </Section>

        <Section
          title="Incoming voice reports"
          id="feed"
          aside={<span className="text-xs text-ink-3 tnum">{voiceJobs.length}</span>}
        >
          {voiceJobs.length === 0 ? (
            <p className="text-sm text-ink-3">
              No voice reports yet. Call the intake agent (button at the bottom right). New reports appear here within a few seconds.
            </p>
          ) : (
            <ul className="space-y-2">
              {voiceJobs.map((j) => (
                <li key={j.job_id}>
                  <button
                    type="button"
                    onClick={() => {
                      setFocus({ lon: j.lon, lat: j.lat, key: `${j.job_id}-${Date.now()}` });
                      setSelectedCrew(j.crew);
                    }}
                    className="w-full rounded-lg border border-sky-400/20 bg-sky-400/5 px-3 py-2 text-left hover:border-sky-400/40"
                  >
                    <div className="flex items-center justify-between gap-2 text-sm">
                      <span className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-sky-300" aria-hidden="true" />
                        <span className="font-mono font-semibold text-sky-100">{j.job_id}</span>
                        <span className="text-ink-2">{short(j.service_name)}</span>
                      </span>
                      <span className="text-xs text-ink-3">
                        {j.crew ? <>→ {j.crew} · +{hm(j.eta_min)}</> : "not yet planned"}
                      </span>
                    </div>
                    {j.reason && <p className="mt-1 text-xs leading-relaxed text-ink-2">{j.reason}</p>}
                    {j.report_count > 1 && <p className="mt-0.5 text-xs text-ink-3">{j.report_count} reports at this spot</p>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          title="Crews"
          id="crews"
          aside={
            selectedCrew ? (
              <button type="button" onClick={() => setSelectedCrew(null)} className="text-xs text-accent hover:underline">
                Show all
              </button>
            ) : (
              <span className="text-xs text-ink-3">select to isolate</span>
            )
          }
        >
          {crewIds.length === 0 ? (
            <p className="text-sm text-ink-3">{error ? "No crew data." : "Loading crews…"}</p>
          ) : (
            <ul className="space-y-1">
              {crewIds.map((id) => {
                const c = crewMeta.get(id);
                const r = routeBy.get(id);
                const active = activeIds.has(id);
                const sel = selectedCrew === id;
                const shift = c?.shift_min ?? 480;
                return (
                  <li key={id}>
                    <button
                      type="button"
                      aria-pressed={sel}
                      disabled={!active}
                      onClick={() => setSelectedCrew(sel ? null : id)}
                      className={`grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm ${
                        sel ? "bg-surface-2 ring-1 ring-line" : "hover:bg-surface-2/60"
                      } ${active ? "" : "cursor-not-allowed opacity-45"}`}
                    >
                      <span className="h-3 w-3 rounded-full" style={{ background: crewColor(id, crewIds) }} aria-hidden="true" />
                      <span className="min-w-0">
                        <span className="flex items-baseline gap-2">
                          <span className="font-mono font-semibold">{id}</span>
                          <span className="truncate text-xs text-ink-3">{c?.skill === "bylaw" ? "Bylaw officer" : "Roads crew"}</span>
                        </span>
                        {active && r ? (
                          <span className="mt-1 block h-1 overflow-hidden rounded-full bg-zinc-800" aria-hidden="true">
                            <span
                              className="block h-full rounded-full"
                              style={{ width: `${Math.min(100, ((r.minutes ?? 0) / shift) * 100)}%`, background: crewColor(id, crewIds) }}
                            />
                          </span>
                        ) : null}
                      </span>
                      <span className="text-right text-xs text-ink-3 tnum">
                        {active && r ? (
                          <>
                            <span className="text-ink-2">{r.stops.length} stops</span> · {ticketsBy.get(id) ?? 0} tix
                            <br />
                            done +{hm(r.minutes)} · {num(r.km, 0)} km
                          </>
                        ) : (
                          "Out today"
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Section>

        <div className="px-4 py-3 text-xs text-ink-3">
          ETA = minutes into the crew&apos;s 8-hour shift from the OR-Tools plan. Historical 311 tickets sit at community centrepoints; voice reports carry exact coordinates.
        </div>
      </aside>

      {/* ---------------------------------------------------------------- map */}
      <div className="relative min-w-0 flex-1">
        <OpsMap
          routes={routes}
          stops={stops}
          depots={depots}
          voice={voice}
          selectedCrew={selectedCrew}
          onSelectCrew={setSelectedCrew}
          focus={focus}
          ariaLabel="Map of today's crew routes and open snow and ice tickets in Calgary"
        />
        <div className="pointer-events-none absolute left-3 top-3">
          <MapLegend showVoice roadGeometry={roadGeometry} />
        </div>
        <div className="pointer-events-none absolute right-14 top-3 flex w-80 flex-col gap-2" role="status" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className="pointer-events-auto rounded-lg border border-sky-400/40 bg-[#0e1a24]/95 px-3 py-2.5 shadow-xl shadow-black/40">
              <div className="flex items-center gap-2 text-sm font-semibold text-sky-100">
                <span className="h-2 w-2 rounded-full bg-sky-300" aria-hidden="true" />
                {t.title}
              </div>
              <div className="mt-1 text-xs leading-relaxed text-sky-100/80">{t.body}</div>
            </div>
          ))}
        </div>
      </div>

      {agentId ? (
        <>
          {/* Widget 0.18.x ignores action-text/start-call-text; labels come from text-contents.
              Pinned so the widget can't change under us during the demo. */}
          <elevenlabs-convai
            agent-id={agentId}
            mic-muting="true"
            text-contents={JSON.stringify({
              main_label: "Report snow or ice by voice",
              start_call: "Talk to SnowTech 311",
              end_call: "End call",
              mute_microphone: "Mute microphone",
            })}
          ></elevenlabs-convai>
          <Script src="https://unpkg.com/@elevenlabs/convai-widget-embed@0.18.3" strategy="afterInteractive" />
        </>
      ) : null}
    </div>
  );
}

function ActionButton({ onClick, busy, disabled, label, hint }: { onClick: () => void; busy: boolean; disabled: boolean; label: string; hint: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-busy={busy}
      className="rounded-lg border border-line bg-surface-2 px-2 py-2 text-left transition-colors hover:border-zinc-600 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span className="block text-sm font-medium text-ink">{busy ? "Replanning…" : label}</span>
      <span className="block text-[11px] text-ink-3">{hint}</span>
    </button>
  );
}

function ReplanCard({ ev }: { ev: ReplanEvent }) {
  const r = ev.result;
  const what =
    ev.action === "surge"
      ? `Surge: ${num(r.new_tickets)} real tickets from ${r.surge_date ? dayLabel(r.surge_date) : "the next day"} landed`
      : ev.action === "restore"
        ? "All crews restored"
        : `${r.crews_out?.length ?? 3} crews out: ${r.crews_out?.join(", ") ?? ""}`;
  return (
    <div className="mt-3 rounded-lg border border-line bg-black/20 px-3 py-2.5">
      <div className="text-xs text-ink-3">
        {what} · {ev.at.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2">
        <div>
          <dt className="text-[11px] text-ink-3">Jobs moved</dt>
          <dd className="text-lg font-semibold">{num(r.jobs_moved)}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-3">Replan</dt>
          <dd className="text-lg font-semibold">
            {r.replan_s.toFixed(1)}
            <span className="text-sm font-normal text-ink-3"> s</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-3">High-risk planned</dt>
          <dd className="text-lg font-semibold">
            {r.high_risk_planned_before}
            <span className="text-sm font-normal text-ink-3"> → </span>
            {r.high_risk_planned_after}
          </dd>
        </div>
      </dl>
    </div>
  );
}
