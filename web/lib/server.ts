import "server-only";
import { promises as fs } from "fs";
import path from "path";

/** Project root (one level above web/). */
export const ROOT = path.resolve(process.cwd(), "..");
export const API = process.env.CIVICSIGNAL_API ?? "http://127.0.0.1:8000";

/** Read one key from the root .env without loading the file into process.env. Never log the value. */
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

let cache: { mtimeMs: number; data: unknown } | null = null;

/** data/results.json, re-read whenever the file changes (so a sim rerun shows up without a rebuild). */
export async function readResults<T>(): Promise<T | null> {
  const p = path.join(ROOT, "data", "results.json");
  try {
    const st = await fs.stat(p);
    if (!cache || cache.mtimeMs !== st.mtimeMs) {
      cache = { mtimeMs: st.mtimeMs, data: JSON.parse(await fs.readFile(p, "utf8")) };
    }
    return cache.data as T;
  } catch {
    return null;
  }
}

export async function readAgentId(): Promise<string | null> {
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
  const st = await fs.stat(path.join(ROOT, "data", "results.json"));
  const policies = {} as ReplaySummary["policies"];
  for (const k of Object.keys(r.policies) as PolicyKey[]) {
    const p = r.policies[k];
    policies[k] = { metrics: p.metrics, replans: p.replans ?? [], daily: p.daily.map((d) => d.info) };
  }
  return { days: r.days, capacity: r.capacity, crews: r.crews, policies, generated_mtime: st.mtime.toISOString() };
}
