import { Check, Clock, X } from "lucide-react";
import { cn } from "../lib/utils.js";

const iconFor = { completed: Check, running: Clock, failed: X, pending: Clock };

export default function PipelineTimeline({ steps }) {
  return (
    <div className="relative space-y-5">
      <div className="absolute bottom-4 left-[13px] top-4 w-px bg-aegis-border" />
      {steps.map((step) => {
        const Icon = iconFor[step.status] || Clock;
        return (
          <div key={step.title} className="relative flex gap-4">
            <div className={cn("z-10 flex h-7 w-7 items-center justify-center rounded-full border", step.status === "completed" && "border-aegis-green bg-aegis-green/15 text-aegis-green shadow-[0_0_18px_rgba(34,197,94,.35)]", step.status === "running" && "animate-pulse border-aegis-blue bg-aegis-blue/15 text-aegis-blue", step.status === "failed" && "border-aegis-red bg-aegis-red/15 text-aegis-red", step.status === "pending" && "border-aegis-border bg-aegis-bg text-aegis-muted")}>
              <Icon className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 pb-1">
              <p className="font-medium text-white">{step.title}</p>
              <p className="text-sm text-aegis-muted">{step.meta || step.timestamp || "Waiting for signal"}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
