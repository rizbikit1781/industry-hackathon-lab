import { readResults } from "@/lib/server";
import type { ResultsFile, PolicyKey } from "@/lib/types";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

/** One policy x one day: routes, markers and day info. ?policy=optimized&day=0 */
export async function GET(req: NextRequest) {
  const r = await readResults<ResultsFile>();
  if (!r) return Response.json({ error: "data/results.json not found" }, { status: 404 });
  const policy = (req.nextUrl.searchParams.get("policy") ?? "optimized") as PolicyKey;
  const day = Number(req.nextUrl.searchParams.get("day") ?? "0");
  const p = r.policies[policy];
  if (!p) return Response.json({ error: `unknown policy ${policy}` }, { status: 400 });
  const d = p.daily[day];
  if (!d) return Response.json({ error: `day index out of range` }, { status: 400 });
  return Response.json(d, { headers: { "Cache-Control": "no-store" } });
}
