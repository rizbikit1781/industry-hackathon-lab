import { readSummary } from "@/lib/server";

export const dynamic = "force-dynamic";

/** Metrics + per-day info for all policies (no geometry), read from data/results.json at request time. */
export async function GET() {
  const s = await readSummary();
  if (!s) {
    return Response.json({ error: "data/results.json not found. Run .venv/bin/python scripts/run_sim.py" }, { status: 404 });
  }
  return Response.json(s, { headers: { "Cache-Control": "no-store" } });
}
