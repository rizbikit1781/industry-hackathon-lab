import { RISK, VOICE_COLOR } from "@/lib/colors";

export default function MapLegend({ showVoice = false, roadGeometry = false }: { showVoice?: boolean; roadGeometry?: boolean }) {
  return (
    <details open className="group pointer-events-auto rounded-lg border border-line bg-surface/90 px-3 py-2 text-xs text-ink-2 shadow-lg shadow-black/30 backdrop-blur">
      <summary className="cursor-pointer list-none font-medium text-ink marker:hidden">
        <span className="inline-flex items-center gap-1.5">
          <span className="text-ink-3 transition-transform group-open:rotate-90" aria-hidden="true">›</span>
          Legend
        </span>
      </summary>
      <div className="mb-1.5 mt-2 font-medium text-ink-2">Open tickets by exposure</div>
      <ul className="space-y-1">
        {(Object.keys(RISK) as (keyof typeof RISK)[]).map((k) => (
          <li key={k} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full ring-2 ring-[#0b0c0e]" style={{ background: RISK[k].color }} aria-hidden="true" />
            {RISK[k].label}
          </li>
        ))}
        <li className="flex items-center gap-2 text-ink-3">
          <span className="h-1.5 w-1.5 rounded-full bg-zinc-500 opacity-60" aria-hidden="true" />
          small, faded = not in today&apos;s plan
        </li>
      </ul>
      <div className="mt-2 space-y-1 border-t border-line pt-2">
        <div className="flex items-center gap-2">
          <span className="h-0.5 w-4 rounded bg-gradient-to-r from-sky-400 via-fuchsia-400 to-amber-300" aria-hidden="true" />
          Crew route (one colour per crew{roadGeometry ? ", road network" : ", straight legs"})
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full border-2 border-zinc-100 bg-[#0b0c0e]" aria-hidden="true" />
          Depot
        </div>
        {showVoice && (
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: VOICE_COLOR, boxShadow: `0 0 0 3px ${VOICE_COLOR}40` }} aria-hidden="true" />
            Voice report (live)
          </div>
        )}
      </div>
    </details>
  );
}
