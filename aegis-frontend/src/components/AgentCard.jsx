import { Bot, Play } from "lucide-react";
import { cn } from "../lib/utils.js";

const tone = {
  running: "border-l-aegis-green text-aegis-green bg-aegis-green/10",
  idle: "border-l-aegis-blue text-aegis-blue bg-aegis-blue/10",
  offline: "border-l-aegis-red text-aegis-red bg-aegis-red/10"
};

export default function AgentCard({ agent, onExecute, busy }) {
  const status = agent.status || "idle";
  return (
    <div className={cn("panel border-l-4 p-5", tone[status]?.split(" ")[0] || "border-l-aegis-muted")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-card border border-aegis-border bg-aegis-bg p-3"><Bot className="h-5 w-5 text-aegis-blue" /></div>
          <div>
            <h3 className="font-semibold text-white">{agent.name}</h3>
            <p className="text-xs uppercase tracking-[0.14em] text-aegis-muted">{agent.type}</p>
          </div>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold capitalize", tone[status]?.replace("border-l-aegis-green", "").replace("border-l-aegis-blue", "").replace("border-l-aegis-red", ""))}>{status}</span>
      </div>
      <div className="mt-5 grid grid-cols-3 gap-2">
        {[["Tasks", agent.tasks], ["Success", agent.success], ["Failed", agent.failed]].map(([label, value]) => (
          <div key={label} className="rounded-button border border-aegis-border bg-aegis-bg/60 p-3">
            <p className="text-xs text-aegis-muted">{label}</p>
            <p className="mt-1 text-lg font-bold text-white">{value ?? 0}</p>
          </div>
        ))}
      </div>
      {status === "running" ? (
        <div className="mt-4 h-2 rounded-full bg-aegis-bg">
          <div className="h-2 rounded-full bg-aegis-green transition-all" style={{ width: `${agent.progress || 64}%` }} />
        </div>
      ) : null}
      <button onClick={() => onExecute(agent.type)} disabled={busy} className="gradient-button mt-5 w-full"><Play className="h-4 w-4" /> Execute</button>
    </div>
  );
}
