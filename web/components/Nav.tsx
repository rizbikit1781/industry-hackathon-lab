"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Live ops" },
  { href: "/replay", label: "Storm-week replay" },
  { href: "/about", label: "How it works" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-line bg-surface px-4">
      <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-ink">
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="3.2" fill="#3987e5" />
          <circle cx="12" cy="12" r="7" fill="none" stroke="#3987e5" strokeOpacity="0.55" strokeWidth="1.6" />
          <circle cx="12" cy="12" r="10.6" fill="none" stroke="#3987e5" strokeOpacity="0.25" strokeWidth="1.4" />
        </svg>
        SnowTech
        <span className="hidden text-xs font-normal text-ink-3 lg:inline">Calgary 311 snow &amp; ice dispatch</span>
      </Link>
      <nav aria-label="Primary">
        <ul className="flex items-center gap-1 text-sm">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 transition-colors ${
                    active ? "bg-surface-2 text-ink" : "text-ink-3 hover:bg-surface-2/60 hover:text-ink-2"
                  }`}
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
