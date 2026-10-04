import "server-only";
import { promises as fs } from "fs";
import path from "path";

/** Project root (one level above web/). Only present when running from the full repo (local demo). */
export const ROOT = path.resolve(process.cwd(), "..");
/** FastAPI engine base URL (server-side only). Same default as next.config.ts. */
export const API = process.env.SNOWTECH_API_URL || process.env.CIVICSIGNAL_API || "http://127.0.0.1:8000";

/**
 * Read one key: process.env first (Vercel), else the root .env (local) without loading the file
 * into process.env. Never log the value.
 */
export async function readEnvKey(name: string): Promise<string | undefined> {
  if (process.env[name]) return process.env[name];
  try {
    const txt = await fs.readFile(path.join(ROOT, ".env"), "utf8");
    for (const line of txt.split(/\r?\n/)) {
      const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m && m[1] === name) return m[2].replace(/^["']|["']$/g, "");
    }
  } catch {
    /* no .env: key not configured */
  }
  return undefined;
}

/**
 * Replay data: ../data/results.json when running inside the repo (live: a sim rerun shows up
 * without a rebuild), else web/data/results.json, the copy made by scripts/copy-results.mjs at
 * prebuild (what ships to Vercel, where only web/ is deployed).
 */
const RESULTS_CANDIDATES = [
  path.join(ROOT, "data", "results.json"),
  path.join(process.cwd(), "data", "results.json"),
];

async function resultsPath(): Promise<{ p: string; mtimeMs: number; mtime: Date } | null> {
  for (const p of RESULTS_CANDIDATES) {
    try {
      const st = await fs.stat(/*turbopackIgnore: true*/ p);
      return { p, mtimeMs: st.mtimeMs, mtime: st.mtime };
    } catch {
      /* try next */
    }
  }
  return null;
}

let cache: { p: string; mtimeMs: number; data: unknown } | null = null;

/** data/results.json, re-read whenever the file changes (so a sim rerun shows up without a rebuild). */
export async function readResults<T>(): Promise<T | null> {
  const f = await resultsPath();
  if (!f) return null;
  try {
    if (!cache || cache.p !== f.p || cache.mtimeMs !== f.mtimeMs) {
      cache = { p: f.p, mtimeMs: f.mtimeMs, data: JSON.parse(await fs.readFile(/*turbopackIgnore: true*/ f.p, "utf8")) };
    }
    return cache.data as T;
  } catch {
    return null;
  }
}

/** ElevenLabs intake agent id: env SNOWTECH_INTAKE_AGENT_ID, else ../voice/agents.json (local). */
export async function readAgentId(): Promise<string | null> {
  const fromEnv = process.env.SNOWTECH_INTAKE_AGENT_ID?.trim();
  if (fromEnv) return fromEnv;
  try {
    const j = JSON.parse(await fs.readFile(path.join(ROOT, "voice", "agents.json"), "utf8"));
    return typeof j?.agents?.intake === "string" ? j.agents.intake : null;
  } catch {
    return null;
  }
}

import type { PolicyKey, ReplaySummary, ResultsFile } from "./types";

/** Metrics + per-day info for all policies (no geometry). */
export async function readSummary(): Promise<ReplaySummary | null> {
  const r = await readResults<ResultsFile>();
  if (!r) return null;
  const f = await resultsPath();
  const policies = {} as ReplaySummary["policies"];
  for (const k of Object.keys(r.policies) as PolicyKey[]) {
    const p = r.policies[k];
    policies[k] = { metrics: p.metrics, replans: p.replans ?? [], daily: p.daily.map((d) => d.info) };
  }
  return {
    days: r.days,
    capacity: r.capacity,
    crews: r.crews,
    policies,
    generated_mtime: (f?.mtime ?? new Date(0)).toISOString(),
  };
}
