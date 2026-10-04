import Dashboard from "@/components/Dashboard";
import { computeNeighbourhoodFlags } from "@/lib/data/flags";

export const dynamic = "force-dynamic";

interface Idea {
  icon: string;
  title: string;
  description: string;
}

// Future-feature concepts for the hail tracker, shown as inspiration cards.
const IDEAS: Idea[] = [
  {
    icon: "📡",
    title: "Live radar overlay",
    description:
      "Layer Environment Canada radar and lightning tiles on the map so a flagged community shows the live storm cell, not just a static risk band.",
  },
  {
    icon: "🔔",
    title: "Push + SMS storm alerts",
    description:
      "When a community flips to flagged, auto-notify 311 dispatch and opted-in residents by SMS or push before hail arrives.",
  },
  {
    icon: "🧾",
    title: "Claims heatmap overlay",
    description:
      "Once real insurance data lands, blend historical claim density with hail_track so the model learns from outcomes, not just path geometry.",
  },
  {
    icon: "⏱️",
    title: "Storm timeline replay",
    description:
      "Scrub through a storm's lifetime using radar snapshots every 10 minutes to see which neighbourhoods the cell actually crossed.",
  },
  {
    icon: "📈",
    title: "Risk score trends",
    description:
      "Track each community's score across multiple storm seasons to flag chronic hot spots for roofing and insurance outreach.",
  },
  {
    icon: "📷",
    title: "Crowd-sourced hail reports",
    description:
      "Let residents submit hail size and photos; use reports to validate or correct the scenario-based hail_track bands.",
  },
];

export default async function Home() {
  const flags = await computeNeighbourhoodFlags();

  return (
    <main className="flex-1 bg-zinc-50 text-zinc-950">
      <div className="mx-auto max-w-7xl px-6 py-10 sm:px-12">
        <header className="flex flex-wrap items-center justify-between gap-6 border-b border-zinc-200 pb-6">
          <div className="flex items-center gap-3">
            <span className="text-4xl" aria-hidden>
              ⛈️
            </span>
            <div>
              {/* <p className="text-sm font-medium text-indigo-600">
                Calgary &middot; Case 4
              </p> */}
              <h1 className="mt-1 text-3xl font-semibold tracking-tight">
                HailsTech Calgary
              </h1>
            </div>
          </div>
          <p className="max-w-sm text-sm text-zinc-500">
            Neighbourhood-level hail tracking for the 5 Aug 2024-style
            north-city storm path &mdash; a short, defensible flag list
            instead of &ldquo;the whole city.&rdquo;
          </p>
        </header>

        <section className="py-8" aria-labelledby="assessments">
          <h2 id="assessments" className="text-lg font-semibold text-zinc-900">
            Live assessment
          </h2>
          <div className="mt-4">
            <Dashboard initial={flags} />
          </div>
        </section>

        <section className="border-t border-zinc-200 py-10" aria-labelledby="ideas">
          <h2 id="ideas" className="text-lg font-semibold text-zinc-900">
            What&apos;s next: ideas for a smarter hail tracker
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-zinc-500">
            Concepts worth prototyping once this flag list is proven out.
          </p>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {IDEAS.map((idea) => (
              <div
                key={idea.title}
                className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
              >
                <div className="text-2xl" aria-hidden>
                  {idea.icon}
                </div>
                <h3 className="mt-2 text-sm font-semibold text-zinc-900">
                  {idea.title}
                </h3>
                <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                  {idea.description}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
