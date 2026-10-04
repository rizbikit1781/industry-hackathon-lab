import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { readSummary } from "@/lib/server";
import { num, pct } from "@/lib/format";

export const metadata: Metadata = { title: "How it works · CivicSignal" };

const STEPS = [
  {
    n: "1",
    name: "Data",
    body: "Every input is City of Calgary open data: 311 snow and ice requests, the civic census, the Equity Index, schools, hospitals and clinics, child care, traffic volumes, transit stops, crosswalks and streetlight poles. It is rolled up onto a 200 m grid covering the city (about 21,000 cells).",
  },
  {
    n: "2",
    name: "Risk",
    body: "Each ticket gets an exposure score: how likely it is that seniors, children, patients, transit riders or heavy foot and car traffic are on that ice. The score is a weighted sum a supervisor can read and change, and every ranking comes with its reasons in words (for example “high 75+ share, near seniors' residence”). It ranks exposure; it does not predict falls.",
  },
  {
    n: "3",
    name: "Solver",
    body: "Google OR-Tools builds each crew's route for the day: bylaw officers for sidewalks, Roads crews for roads and pathways. It respects skills, the 8-hour shift and ticket capacity, and trades driving distance against priority, so the riskiest ice is served first without crews crossing the city for one ticket.",
  },
  {
    n: "4",
    name: "Replan",
    body: "When crews call in sick or a second snowfall brings a surge of reports, the solver re-plans in a few seconds. A stability penalty keeps most crews on the route they already have, so dispatchers see only the jobs that had to move.",
  },
  {
    n: "5",
    name: "Voice",
    body: "Residents report by talking to an ElevenLabs voice agent. It asks what and where, reads the details back, then creates the ticket. The engine geocodes it, scores it and inserts it into a crew's route in about 3 seconds, and the agent tells the caller why it ranks where it does. Emergencies are sent to 9-1-1, never ticketed.",
  },
];

export default async function About() {
  await connection();
  const s = await readSummary();
  const f = s?.policies.fifo.metrics;
  const o = s?.policies.optimized.metrics;
  const d = s?.policies.optimized_disruption;

  return (
    <div className="cs-scroll min-h-0 flex-1 overflow-y-auto">
      <article className="mx-auto max-w-4xl px-6 py-10">
        <p className="text-sm font-medium text-accent">How it works</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">The right crew to the riskiest ice first</h1>
        <p className="mt-3 max-w-2xl text-base leading-relaxed text-ink-2">
          CivicSignal is a dispatch engine for Calgary&apos;s 311 snow and ice crews. A language model handles the conversation; the schedule comes
          from an optimisation solver, so every plan is feasible, repeatable and explainable.
        </p>

        {f && o ? (
          <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-line bg-surface px-4 py-3">
              <div className="text-xs text-ink-3">High-risk tickets served within 48 h</div>
              <div className="mt-1 text-2xl font-semibold">
                {pct(f.high_risk_within_48h, 1)} <span className="text-ink-3">→</span> {pct(o.high_risk_within_48h, 1)}
              </div>
              <div className="mt-1 text-xs text-ink-3">oldest-first vs CivicSignal</div>
            </div>
            <div className="rounded-lg border border-line bg-surface px-4 py-3">
              <div className="text-xs text-ink-3">Km driven in the storm week</div>
              <div className="mt-1 text-2xl font-semibold">
                {num(f.total_km)} <span className="text-ink-3">→</span> {num(o.total_km)}
              </div>
              <div className="mt-1 text-xs text-ink-3">{pct(o.total_km / f.total_km - 1)} with the same crews</div>
            </div>
            <div className="rounded-lg border border-line bg-surface px-4 py-3">
              <div className="text-xs text-ink-3">Replan after a disruption</div>
              <div className="mt-1 text-2xl font-semibold">
                {d?.metrics.replan_s_max != null ? `${d.metrics.replan_s_max.toFixed(1)} s` : "—"}
              </div>
              <div className="mt-1 text-xs text-ink-3">
                {d?.metrics.jobs_moved_per_replan != null ? `${num(d.metrics.jobs_moved_per_replan)} jobs moved per replan on average` : "no replans recorded"}
              </div>
            </div>
          </div>
        ) : (
          <p className="mt-8 text-sm text-ink-3">Replay results not found (run scripts/run_sim.py to generate data/results.json).</p>
        )}

        <h2 className="mt-12 text-xl font-semibold tracking-tight">Architecture</h2>
        <ol className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-5" aria-label="Pipeline from data to voice">
          {STEPS.map((st, i) => (
            <li key={st.n} className="relative rounded-lg border border-line bg-surface px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="grid h-6 w-6 place-items-center rounded-full bg-accent/15 text-xs font-semibold text-accent">{st.n}</span>
                <span className="font-semibold">{st.name}</span>
              </div>
              {i < STEPS.length - 1 && (
                <span className="absolute -right-2.5 top-4 z-10 hidden text-ink-3 md:block" aria-hidden="true">
                  →
                </span>
              )}
            </li>
          ))}
        </ol>
        <div className="mt-6 space-y-5">
          {STEPS.map((st) => (
            <section key={st.n} aria-labelledby={`step-${st.n}`}>
              <h3 id={`step-${st.n}`} className="text-base font-semibold">
                {st.n}. {st.name}
              </h3>
              <p className="mt-1 leading-relaxed text-ink-2">{st.body}</p>
            </section>
          ))}
        </div>

        <h2 className="mt-12 text-xl font-semibold tracking-tight">How we tested it</h2>
        <p className="mt-2 leading-relaxed text-ink-2">
          We replayed Calgary&apos;s real storm week (Nov 25 – Dec 1, 2025) three ways with the same crews and the same daily capacity, calibrated to
          the City&apos;s median real closures: oldest-first (FIFO), CivicSignal, and CivicSignal with 30% of crews out on day 3 plus a mid-day surge on
          day 7. See the <Link href="/replay" className="text-accent hover:underline">storm-week replay</Link> for every metric, including where
          CivicSignal does worse.
        </p>

        <h2 className="mt-12 text-xl font-semibold tracking-tight">Honest limits</h2>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 leading-relaxed text-ink-2">
          <li>Triage has a cost: with capacity at about half of demand, CivicSignal serves fewer low-risk tickets and has a longer worst-case (p90) wait than FIFO.</li>
          <li>Public 311 tickets are placed at community centrepoints, so historical tickets get their community&apos;s average exposure. Voice reports carry exact coordinates.</li>
          <li>The pedestrian proxy and duplicate detection did not validate on public data; both are reported, not hidden.</li>
          <li>Risk weights, service times and depot locations are assumptions a supervisor would tune. FIFO is our model of a no-triage queue, not the City&apos;s real dispatch.</li>
        </ul>

        <h2 className="mt-12 text-xl font-semibold tracking-tight">Under the hood</h2>
        <p className="mt-2 leading-relaxed text-ink-2">
          Python (pandas, scikit-learn, OR-Tools) and a FastAPI engine hold the state; there is no database. This Next.js console reads the live plan
          from the engine every few seconds and the replay from <code className="font-mono text-sm">data/results.json</code>. Map tiles: CARTO Dark
          Matter over OpenStreetMap, rendered with MapLibre GL.
        </p>
      </article>
    </div>
  );
}
