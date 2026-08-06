import { Bell, LogOut, Menu, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth.js";

export default function Topbar({ title }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const handleLogout = () => { logout(); navigate("/login"); };
  return (
    <header className="sticky top-0 z-20 border-b border-aegis-border bg-aegis-bg/75 px-4 py-4 backdrop-blur-xl md:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <button className="ghost-button px-3 xl:hidden" aria-label="Open navigation"><Menu className="h-4 w-4" /></button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-bold text-white md:text-2xl">{title}</h1>
          <div className="mt-1 inline-flex items-center gap-2 rounded-full border border-aegis-green/30 bg-aegis-green/10 px-3 py-1 text-xs font-semibold text-aegis-green">
            <span className="h-2 w-2 animate-pulse rounded-full bg-aegis-green" /> All Systems Operational
          </div>
        </div>
        <Link to="/pipelines" className="gradient-button hidden sm:inline-flex"><Plus className="h-4 w-4" /> New Pipeline</Link>
        <button className="ghost-button px-3" aria-label="Notifications"><Bell className="h-4 w-4" /></button>
        <div className="group relative">
          <button className="flex items-center gap-2 rounded-button border border-aegis-border bg-aegis-card px-2.5 py-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-aegis-purple/20 text-sm font-bold text-aegis-purple">{user?.name?.[0] || "A"}</span>
            <span className="hidden text-sm font-medium text-white md:block">{user?.name}</span>
          </button>
          <div className="invisible absolute right-0 mt-2 w-48 rounded-card border border-aegis-border bg-aegis-card p-2 opacity-0 shadow-xl transition group-hover:visible group-hover:opacity-100">
            <p className="truncate px-3 py-2 text-xs text-aegis-muted">{user?.email}</p>
            <button onClick={handleLogout} className="flex w-full items-center gap-2 rounded-button px-3 py-2 text-left text-sm text-aegis-text hover:bg-aegis-bg"><LogOut className="h-4 w-4" /> Logout</button>
          </div>
        </div>
      </div>
    </header>
  );
}
