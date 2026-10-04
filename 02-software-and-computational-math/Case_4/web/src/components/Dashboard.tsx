"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import type { FlagResult } from "@/lib/data/flags";

const FlagMap = dynamic(() => import("./FlagMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-sm text-zinc-500">
      Loading map…
    </div>
  ),
});

const HAIL_ICON: Record<"high" | "medium" | "low", string> = {
  high: "⛈️",
  medium: "🌦️",
  low: "🌤️",
};

interface DashboardProps {
  initial: FlagResult;
}

export default function Dashboard({ initial }: DashboardProps) {
  const [activeFlag, setActiveFlag] = useState<"flag_v1" | "flag_v2">("flag_v1");

  const flaggedRows = useMemo(
    () =>
      [...initial.rows]
        .filter((r) => r[activeFlag])
        .sort((a, b) => a.hail_track.localeCompare(b.hail_track)),
    [initial.rows, activeFlag],
  );

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
      <aside className="flex flex-col gap-6">
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-zinc-700">Flag rule</h3>
          <div className="mt-3 flex flex-col gap-2 text-xs">
            <button
              onClick={() => setActiveFlag("flag_v1")}
              className={`rounded px-2 py-1 text-left ${activeFlag === "flag_v1" ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600"}`}
            >
              v1: hail track = high only
            </button>
            <button
              onClick={() => setActiveFlag("flag_v2")}
              className={`rounded px-2 py-1 text-left ${activeFlag === "flag_v2" ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600"}`}
            >
              v2: hail track = high or medium
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm">
          <h3 className="text-sm font-semibold text-zinc-700">Storm outlook</h3>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <StatTile
              icon={HAIL_ICON.high}
              label="High"
              value={initial.summary.highCount}
              tone="text-red-600"
            />
            <StatTile
              icon={HAIL_ICON.medium}
              label="Medium"
              value={initial.summary.mediumCount}
              tone="text-amber-600"
            />
            <StatTile
              icon={HAIL_ICON.low}
              label="Low"
              value={initial.summary.lowCount}
              tone="text-emerald-600"
            />
          </div>
          <dl className="mt-4 space-y-1.5 text-zinc-600">
            <Row label="Downtown-only baseline" value={initial.summary.baselineDowntownCount} />
            <Row label='"Flag everyone" baseline' value={initial.summary.baselineAllCount} />
            <Row label="v1 flagged" value={initial.summary.flagV1Count} />
            <Row label="v2 flagged" value={initial.summary.flagV2Count} />
            <Row label="Flipped v1 ↔ v2" value={initial.summary.flippedCount} />
          </dl>
        </div>

        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-zinc-700">
            Flagged communities ({flaggedRows.length})
          </h3>
          <ul className="mt-3 max-h-80 space-y-1 overflow-y-auto text-xs text-zinc-600">
            {flaggedRows.map((r) => (
              <li key={r.community_name} className="flex justify-between gap-2">
                <span>{r.community_name}</span>
                <span className="text-zinc-400">
                  {HAIL_ICON[r.hail_track]} {r.hail_track}
                </span>
              </li>
            ))}
            {flaggedRows.length === 0 && (
              <li className="text-zinc-400">No communities flagged at this rule.</li>
            )}
          </ul>
        </div>
      </aside>

      <div className="h-[600px] overflow-hidden rounded-lg border border-zinc-200 lg:h-full">
        <FlagMap rows={initial.rows} activeFlag={activeFlag} />
      </div>
    </div>
  );
}

function StatTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: string;
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="rounded-md bg-zinc-50 py-3">
      <div className="text-xl" aria-hidden>
        {icon}
      </div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
      <div className="text-[11px] text-zinc-500">{label}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between">
      <dt>{label}</dt>
      <dd className="font-medium text-zinc-900">{value}</dd>
    </div>
  );
}
