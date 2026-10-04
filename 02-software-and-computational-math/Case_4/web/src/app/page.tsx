import Image from "next/image";
import Dashboard from "@/components/Dashboard";
import { computeNeighbourhoodFlags } from "@/lib/data/flags";
import { isSupabaseConfigured } from "@/lib/supabase/config";

export const dynamic = "force-dynamic";

export default async function Home() {
  const configured = isSupabaseConfigured();
  const flags = await computeNeighbourhoodFlags();

  return (
    <main className="flex-1 bg-zinc-50 px-6 py-10 text-zinc-950 sm:px-12">
      <header className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-6 border-b border-zinc-200 pb-6">
        <div>
          <p className="text-sm font-medium text-zinc-500">Calgary / Case 4</p>
          <h1 className="mt-2 text-3xl font-semibold">Neighbourhood flags</h1>
        </div>
        <Image src="/next.svg" alt="Next.js" width={100} height={20} priority />
      </header>
      <section className="mx-auto max-w-6xl py-8" aria-labelledby="assessments">
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <dt className="text-zinc-500">Supabase configuration</dt>
          <dd className={configured ? "text-emerald-700" : "text-zinc-600"}>
            {configured ? "Configured" : "Not configured"}
          </dd>
        </dl>
        <h2 id="assessments" className="mt-12 text-lg font-semibold">
          Assessments
        </h2>
        <div className="mt-4 border-t border-zinc-200 pt-8">
          <Dashboard initial={flags} />
        </div>
      </section>
    </main>
  );
}
