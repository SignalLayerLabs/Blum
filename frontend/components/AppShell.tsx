"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, Brain, Clock, Copy, Cpu, Dumbbell, TrendingUp, FlaskConical, type LucideIcon } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { SystemStatus } from "@/lib/types";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  aliases?: string[];
};

const nav: NavItem[] = [
  { href: "/brain", label: "Brain", icon: Brain, aliases: ["/dashboard"] },
  { href: "/training-ground", label: "Training Ground", icon: Dumbbell, aliases: ["/learning"] },
  { href: "/paper-trading", label: "Paper Trading", icon: Copy, aliases: ["/copy-trading"] },
  { href: "/alpha", label: "Alpha", icon: TrendingUp },
  { href: "/evolution", label: "Evolution", icon: FlaskConical }
];

type SidebarStatus = {
  workerStatus: string;
  modelStatus: string;
  lastLearningCycle: string;
  paperForwardStatus: string;
  alphaEvidenceGrade: string;
};

const defaultSidebarStatus: SidebarStatus = {
  workerStatus: "checking",
  modelStatus: "checking",
  lastLearningCycle: "checking",
  paperForwardStatus: "checking",
  alphaEvidenceGrade: "checking",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [sidebarStatus, setSidebarStatus] = useState<SidebarStatus>(defaultSidebarStatus);

  useEffect(() => {
    let mounted = true;
    const onPaperTrading = pathname === "/paper-trading" || pathname === "/copy-trading" || pathname.startsWith("/paper-trading/") || pathname.startsWith("/copy-trading/");
    const onAlpha = pathname === "/alpha" || pathname.startsWith("/alpha/");
    if (onPaperTrading) {
      api.traderPaperTrading(50).then((paper) => {
        if (!mounted) return;
        setSidebarStatus({
          workerStatus: "snapshot",
          modelStatus: "paper forward",
          lastLearningCycle: "not queried",
          paperForwardStatus: compactStatus(paper?.snapshot_status ?? paper?.status),
          alphaEvidenceGrade: "not queried",
        });
      }).catch(() => {
        if (mounted) {
          setSidebarStatus({
            workerStatus: "snapshot",
            modelStatus: "paper forward",
            lastLearningCycle: "not queried",
            paperForwardStatus: "unavailable",
            alphaEvidenceGrade: "not queried",
          });
        }
      });
      return () => {
        mounted = false;
      };
    }
    if (onAlpha) {
      setSidebarStatus({
        workerStatus: "snapshot",
        modelStatus: "alpha evidence",
        lastLearningCycle: "not queried",
        paperForwardStatus: "not queried",
        alphaEvidenceGrade: "see page",
      });
      return () => {
        mounted = false;
      };
    }
    api.systemStatus().then((system) => {
      if (!mounted) return;
      setSystemStatus(system);
      setSidebarStatus({
        workerStatus: system?.runtime_flags?.autonomous_engine_enabled ? "workers on" : "workers off",
        modelStatus: system?.runtime_flags?.financial_brain_model_enabled ? "model active" : "snapshot mode",
        lastLearningCycle: "see Training",
        paperForwardStatus: "see Paper",
        alphaEvidenceGrade: "see Alpha",
      });
    }).catch(() => {
      if (mounted) setSidebarStatus(defaultSidebarStatus);
    });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div>
            <strong>BLUM</strong>
            <span>Trader Brain</span>
          </div>
        </div>
        <div className="sidebar-market-state">
          <Activity size={15} />
          <div>
            <strong>{sidebarStatus.workerStatus}</strong>
            <span>{sidebarStatus.modelStatus}</span>
          </div>
        </div>
        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            const active =
              pathname === item.href ||
              (item.href === "/brain" && pathname === "/") ||
              item.aliases?.some((alias) => pathname === alias || pathname.startsWith(`${alias}/`)) ||
              pathname.startsWith(`${item.href}/`);
            return (
              <Link href={item.href} key={item.href} className={clsx("nav-item", active && "active")}>
                <Icon size={17} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="system-card">
          <div><Activity size={15} /> Worker: {sidebarStatus.workerStatus}</div>
          <div><Cpu size={15} /> Model: {sidebarStatus.modelStatus}</div>
          <div><Clock size={15} /> Last learning: {sidebarStatus.lastLearningCycle}</div>
          <div><Copy size={15} /> Paper forward: {sidebarStatus.paperForwardStatus}</div>
          <div><Brain size={15} /> Alpha evidence: {sidebarStatus.alphaEvidenceGrade}</div>
          <span>v{systemStatus?.app_version ?? "loading"}</span>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}

function compactStatus(value: any) {
  if (!value) return "pending";
  const text = String(value);
  if (text.includes("T")) {
    try {
      return new Date(text).toLocaleDateString();
    } catch {
      return text;
    }
  }
  return text.replaceAll("_", " ").slice(0, 28);
}
