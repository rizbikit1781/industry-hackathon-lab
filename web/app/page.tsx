import { connection } from "next/server";
import LiveConsole from "@/components/LiveConsole";
import { readAgentId, readResults } from "@/lib/server";
import type { ResultsFile } from "@/lib/types";

export default async function Page() {
  await connection();
  const [agentId, results] = await Promise.all([readAgentId(), readResults<ResultsFile>()]);
  return <LiveConsole agentId={agentId} allCrews={results?.crews ?? []} />;
}
