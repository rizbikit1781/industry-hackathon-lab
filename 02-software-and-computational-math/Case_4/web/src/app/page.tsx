import Image from "next/image";
import { isSupabaseConfigured } from "@/lib/supabase/config";

export const dynamic = "force-dynamic";

export default function Home() {
  const configured = isSupabaseConfigured();

  return (
    <main className="flex-1 bg-zinc-50 px-6 py-10 text-zinc-950 sm:px-12">
      <header className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-6 border-b border-zinc-200 pb-6">
        <div>
          <p className="text-sm font-medium text-zinc-500">Calgary / Case 4</p>
          <h1 className="mt-2 text-3xl font-semibold">Neighbourhood flags</h1>
        </div>
        <Image src="/next.svg" alt="Next.js" width={100} height={20} priority />
      </header>
      <section className="mx-auto max-w-5xl py-8" aria-labelledby="assessments">
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <dt className="text-zinc-500">Supabase configuration</dt>
          <dd className={configured ? "text-emerald-700" : "text-zinc-600"}>
            {configured ? "Configured" : "Not configured"}
          </dd>
        </dl>
        <h2 id="assessments" className="mt-12 text-lg font-semibold">
          Assessments
        </h2>
        <p className="mt-4 border-t border-zinc-200 py-8 text-sm text-zinc-500">
          No assessments yet.
        </p>
      </section>
    </main>
  );
}
