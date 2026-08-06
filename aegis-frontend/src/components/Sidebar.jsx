import { BarChart3, Bot, GitBranch, LayoutDashboard, MessageSquare, PauseCircle, Shield, Upload, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "../lib/utils.js";
import { useAuth } from "../hooks/useAuth.js";
import api from "../lib/api.js";

const sections = [
  { title: "Overview", items: [{ label: "Dashboard", path: "/", icon: LayoutDashboard }, { label: "Pipelines", path: "/pipelines", icon: GitBranch }, { label: "Agents", path: "/agents", icon: Bot }] },
  { title: "Intelligence", items: [{ label: "Chat", path: "/chat", icon: MessageSquare }, { label: "Lineage", path: "/lineage", icon: GitBranch }] },
  { title: "Operations", items: [{ label: "Approvals", path: "/approvals", icon: PauseCircle, badgeKey: "approvals" }, { label: "Monitoring", path: "/monitoring", icon: BarChart3 }, { label: "Upload", path: "/upload", icon: Upload }] }
];

export default function Sidebar() {
  const { user, isAdmin } = useAuth();
  const [approvalCount, setApprovalCount] = useState(0);
  const canApprove = isAdmin || user?.role === "data_engineer";

  const refreshApprovalCount = useCallback(() => {
    if (!canApprove) {
      setApprovalCount(0);
      return;
    }
    api.get("/approvals/pending").then(({ data }) => {
      const approvals = Array.isArray(data) ? data : data.approvals || data.pipelines || [];
      setApprovalCount(approvals.length);
    }).catch(() => setApprovalCount(0));
  }, [canApprove]);

  useEffect(() => {
    refreshApprovalCount();
    window.addEventListener("aegis-approvals-updated", refreshApprovalCount);
    return () => window.removeEventListener("aegis-approvals-updated", refreshApprovalCount);
  }, [refreshApprovalCount]);

  const allSections = isAdmin ? [...sections, { title: "Admin", items: [{ label: "Admin", path: "/admin", icon: Users }] }] : sections;
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[260px] border-r border-aegis-border bg-aegis-bg/88 px-4 py-5 backdrop-blur xl:block">
      <div className="mb-8 flex items-center gap-3 px-2">
        <div className="rounded-card border border-aegis-border bg-gradient-to-br from-aegis-blue to-aegis-purple p-2"><Shield className="h-6 w-6 text-white" /></div>
        <div>
          <div className="bg-gradient-to-r from-aegis-blue to-aegis-purple bg-clip-text text-xl font-extrabold text-transparent">Aegis AI</div>
          <p className="text-xs text-aegis-muted">v2.0 command center</p>
        </div>
      </div>
      <nav className="space-y-6">
        {allSections.map((section) => (
          <div key={section.title}>
            <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-aegis-muted">{section.title}</p>
            <div className="space-y-1">
              {section.items.map((item) => (
                <NavLink key={item.path} to={item.path} end={item.path === "/"} className={({ isActive }) => cn("flex items-center gap-3 rounded-button border-l-2 px-3 py-2.5 text-sm font-medium transition", isActive ? "border-aegis-blue bg-aegis-blue/12 text-white" : "border-transparent text-aegis-muted hover:bg-aegis-card hover:text-white")}>
                  <item.icon className="h-4 w-4" />
                  <span className="flex-1">{item.label}</span>
                  {item.badgeKey === "approvals" && approvalCount > 0 ? <span className="rounded-full bg-aegis-orange/15 px-2 py-0.5 text-xs text-aegis-orange">{approvalCount}</span> : null}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="absolute bottom-5 left-4 right-4 rounded-card border border-aegis-border bg-aegis-card p-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-aegis-blue/20 text-sm font-bold text-aegis-blue">{user?.name?.[0] || "A"}</div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">{user?.name}</p>
            <p className="truncate text-xs capitalize text-aegis-muted">{user?.role}</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
