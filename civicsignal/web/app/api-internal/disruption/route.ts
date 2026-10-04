import { API, readEnvKey } from "@/lib/server";

export const dynamic = "force-dynamic";

/**
 * Server-side forwarder for POST /disruption. Adds X-CivicSignal-Key from the root .env
 * (never sent to the browser). Only the three demo shapes are allowed through.
 */
export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ detail: "invalid JSON" }, { status: 400 });
  }
  const clean: Record<string, unknown> = {};
  if (body.surge === true) clean.surge = true;
  else if (typeof body.crews_out === "number" && body.crews_out >= 0 && body.crews_out <= 17) {
    clean.crews_out = Math.floor(body.crews_out);
    if (body.skill === "bylaw" || body.skill === "roads") clean.skill = body.skill;
  } else {
    return Response.json({ detail: "send {crews_out:int} or {surge:true}" }, { status: 422 });
  }
  const key = await readEnvKey("CIVICSIGNAL_KEY");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (key) headers["X-CivicSignal-Key"] = key;
  try {
    const res = await fetch(`${API}/disruption`, {
      method: "POST",
      headers,
      body: JSON.stringify(clean),
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return Response.json(
      { detail: "API not reachable on :8000. Start it with .venv/bin/uvicorn civicsignal.api:app --port 8000" },
      { status: 502 },
    );
  }
}
