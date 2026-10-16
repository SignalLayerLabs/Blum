"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  ChartNoAxesCombined,
  FlaskConical,
  LayoutDashboard,
  ListOrdered,
  ShieldCheck,
} from "lucide-react";
const nav = [
  {
    href: "/brain",
    label: "Overview",
    icon: LayoutDashboard,
    aliases: ["/", "/dashboard"],
  },
  { href: "/calls", label: "Calls", icon: Activity, aliases: [] },
  {
    href: "/paper-trading",
    label: "Trades",
    icon: ListOrdered,
    aliases: ["/copy-trading"],
  },
  {
    href: "/alpha",
    label: "Performance",
    icon: ChartNoAxesCombined,
    aliases: [],
  },
  {
    href: "/training-ground",
    label: "Research",
    icon: FlaskConical,
    aliases: ["/learning", "/evolution"],
  },
];
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname().replace(/\/+$/, "") || "/";
  const refreshed =
    ["/", "/dashboard", "/copy-trading", "/learning"].includes(path) ||
    nav.some((item) => path === item.href);
  return (
    <div className="blum-shell">
      <a href="#workspace" className="blum-skip">
        Skip to workspace
      </a>
      <aside className="blum-sidebar">
        <Link className="blum-brand" href="/">
          <span className="blum-mark">B</span>
          <div>
            <strong>BLUM</strong>
            <small>Research into decisions</small>
          </div>
        </Link>
        <span className="blum-nav-caption">WORKSPACE</span>
        <nav aria-label="Workspace navigation">
          {nav.map((item) => {
            const active =
              path === item.href ||
              path.startsWith(item.href + "/") ||
              item.aliases.includes(path);
            const Icon = item.icon;
            return (
              <Link
                href={item.href}
                key={item.href}
                className={active ? "blum-nav-link is-active" : "blum-nav-link"}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={18} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="blum-sidebar-bottom">
          <div className="blum-mode">
            <ShieldCheck size={17} />
            <div>
              <strong>Paper environment</strong>
              <span>Research. Simulated execution.</span>
            </div>
          </div>
          <a
            className="blum-docs"
            href="https://github.com/SignalLayerLabs/Blum/tree/main/docs"
            target="_blank"
            rel="noreferrer"
          >
            <BookOpen size={15} />
            How BLUM works
            <ArrowUpRight size={13} />
          </a>
        </div>
      </aside>
      <main id="workspace" className="blum-main">
        <div className="blum-topbar">
          <span>Financial research workspace</span>
          <span className="blum-paper-label">
            <span />
            Paper trading
          </span>
        </div>
        {refreshed ? (
          children
        ) : (
          <div className="blum-legacy-surface">{children}</div>
        )}
      </main>
    </div>
  );
}
