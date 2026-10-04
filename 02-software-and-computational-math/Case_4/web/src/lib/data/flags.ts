import { readFile } from "node:fs/promises";
import path from "node:path";

const DOWNTOWN = new Set([
  "DOWNTOWN COMMERCIAL CORE",
  "DOWNTOWN EAST VILLAGE",
  "DOWNTOWN WEST END",
  "EAU CLAIRE",
  "CHINATOWN",
  "BELTLINE",
]);

export interface NeighbourhoodFlag {
  community_name: string;
  sector: string;
  hail_track: "high" | "medium" | "low";
  latitude: number;
  longitude: number;
  baseline_downtown: boolean;
  baseline_all: boolean;
  /** Narrow rule: only the named high-risk hail path. */
  flag_v1: boolean;
  /** Broad rule: high-risk path plus adjacent medium-risk communities. */
  flag_v2: boolean;
}

export interface FlagSummary {
  totalCommunities: number;
  highCount: number;
  mediumCount: number;
  lowCount: number;
  baselineDowntownCount: number;
  baselineAllCount: number;
  flagV1Count: number;
  flagV2Count: number;
  flippedCount: number;
}

export interface FlagResult {
  rows: NeighbourhoodFlag[];
  summary: FlagSummary;
}

// Minimal CSV parser: the bundled seed has no quoted/escaped commas.
function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/);
  const header = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const cells = line.split(",");
    const row: Record<string, string> = {};
    header.forEach((key, i) => {
      row[key] = cells[i] ?? "";
    });
    return row;
  });
}

async function loadNeighbourhoods() {
  const file = path.join(process.cwd(), "..", "data", "neighbourhoods_hail_scenario.csv");
  const text = await readFile(file, "utf-8");
  return parseCsv(text).map((r) => ({
    community_name: r.community_name,
    sector: r.sector,
    hail_track: r.hail_track as "high" | "medium" | "low",
    latitude: Number(r.latitude),
    longitude: Number(r.longitude),
  }));
}

export async function computeNeighbourhoodFlags(): Promise<FlagResult> {
  const neighbourhoods = await loadNeighbourhoods();

  const rows: NeighbourhoodFlag[] = neighbourhoods.map((n) => ({
    community_name: n.community_name,
    sector: n.sector,
    hail_track: n.hail_track,
    latitude: n.latitude,
    longitude: n.longitude,
    baseline_downtown: DOWNTOWN.has(n.community_name.toUpperCase()),
    baseline_all: true,
    flag_v1: n.hail_track === "high",
    flag_v2: n.hail_track === "high" || n.hail_track === "medium",
  }));

  const summary: FlagSummary = {
    totalCommunities: rows.length,
    highCount: rows.filter((r) => r.hail_track === "high").length,
    mediumCount: rows.filter((r) => r.hail_track === "medium").length,
    lowCount: rows.filter((r) => r.hail_track === "low").length,
    baselineDowntownCount: rows.filter((r) => r.baseline_downtown).length,
    baselineAllCount: rows.filter((r) => r.baseline_all).length,
    flagV1Count: rows.filter((r) => r.flag_v1).length,
    flagV2Count: rows.filter((r) => r.flag_v2).length,
    flippedCount: rows.filter((r) => r.flag_v1 !== r.flag_v2).length,
  };

  return { rows, summary };
}
