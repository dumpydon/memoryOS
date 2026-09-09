"use client";

import {
  Activity,
  ArrowUpRight,
  BrainCircuit,
  ChevronDown,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  Settings2,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useWorkspace } from "@/components/workspace-context";

const navigation = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/memories", label: "Memory explorer", icon: BrainCircuit },
  { href: "/ingestion", label: "Ingestion playground", icon: Inbox },
  { href: "/recall", label: "Recall lab", icon: FlaskConical },
];

export function SidebarNav() {
  const pathname = usePathname();
  const { mode } = useWorkspace();
  return (
    <>
      <div
        className="scope-picker"
        role="group"
        aria-label="Current memory scope"
      >
        <div className="scope-avatar">A</div>
        <div className="scope-copy">
          <span className="eyebrow">Workspace</span>
          <strong>
            {pathname === "/settings"
              ? "Workspace settings"
              : mode === "live"
                ? "Atlas / live"
                : "Atlas / demo"}
          </strong>
        </div>
        <ChevronDown size={15} aria-hidden="true" />
      </div>

      <nav className="side-nav" aria-label="Primary navigation">
        <span className="nav-section-label">Workspace</span>
        {navigation.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              className={`nav-item${active ? " active" : ""}`}
              href={href}
              key={href}
              aria-label={label}
              title={label}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="sidebar-bottom">
        <div className="service-status">
          <span className="status-dot" />
          <span>{mode === "demo" ? "Demo fixture mode" : "Live provider mode"}</span>
          <Activity size={14} aria-hidden="true" />
        </div>
        <Link
          className={`nav-item muted${pathname === "/settings" ? " active" : ""}`}
          href="/settings"
          aria-label="Settings"
          title="Settings"
          aria-current={pathname === "/settings" ? "page" : undefined}
        >
          <Settings2 size={17} strokeWidth={1.8} aria-hidden="true" />
          <span>Settings</span>
        </Link>
        <div className="sidebar-meta">
          <span>MemoryOS v0.1</span>
          <ArrowUpRight size={13} aria-hidden="true" />
        </div>
      </div>
    </>
  );
}
