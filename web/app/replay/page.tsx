import type { Metadata } from "next";
import { connection } from "next/server";
import ReplayView from "@/components/ReplayView";
import { Kbd, Notice } from "@/components/ui";
import { readSummary } from "@/lib/server";

export const metadata: Metadata = { title: "Storm-week replay · CivicSignal" };

export default async function Page() {
  await connection();
  const summary = await readSummary();
  if (!summary) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <Notice tone="error" title="No replay results yet">
          <Kbd>data/results.json</Kbd> was not found. From <Kbd>civicsignal/</Kbd> run <Kbd>.venv/bin/python scripts/run_sim.py</Kbd>, then reload.
        </Notice>
      </div>
    );
  }
  return <ReplayView summary={summary} />;
}
