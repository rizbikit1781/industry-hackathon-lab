import type { ReactNode } from "react";

export function Section({ title, aside, children, id }: { title: string; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section aria-labelledby={id} className="border-b border-line px-4 py-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id={id} className="text-xs font-medium uppercase tracking-wider text-ink-3">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-1 text-2xl font-semibold leading-none tracking-tight text-ink">{value}</div>
      {sub != null && <div className="mt-1.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Notice({ tone = "warn", title, children }: { tone?: "warn" | "error" | "info"; title: string; children?: ReactNode }) {
  const cls =
    tone === "error"
      ? "border-red-500/30 bg-red-950/40 text-red-200"
      : tone === "warn"
        ? "border-amber-500/30 bg-amber-950/40 text-amber-200"
        : "border-sky-500/30 bg-sky-950/40 text-sky-200";
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg border px-3 py-2.5 text-sm ${cls}`}>
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-xs opacity-90">{children}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <code className="rounded bg-black/40 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{children}</code>;
}
