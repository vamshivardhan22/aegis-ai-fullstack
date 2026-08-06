import { Check, Edit3, X } from "lucide-react";
import { useState } from "react";
import { cn } from "../lib/utils.js";

const riskTone = { high: "bg-aegis-red/15 text-aegis-red border-aegis-red/35", medium: "bg-aegis-orange/15 text-aegis-orange border-aegis-orange/35", low: "bg-aegis-green/15 text-aegis-green border-aegis-green/35" };

export default function ApprovalCard({ approval, onApprove, onReject, onModify }) {
  const [leaving, setLeaving] = useState(false);
  const action = async (fn) => { setLeaving(true); await new Promise((resolve) => setTimeout(resolve, 260)); fn(approval.id); };
  return (
    <div className={cn("panel p-5 transition", leaving && "animate-slideAway")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold text-white">{approval.title}</h3>
          <p className="mt-1 text-sm text-aegis-muted">{approval.description}</p>
        </div>
        <span className={cn("rounded-full border px-3 py-1 text-xs font-bold uppercase", riskTone[approval.riskLevel])}>{approval.riskLevel}</span>
      </div>
      <pre className="mt-4 overflow-auto rounded-button border border-aegis-border bg-aegis-bg/80 p-4 text-xs leading-6 text-aegis-muted">{approval.impact}</pre>
      <div className="mt-4 flex flex-wrap gap-3">
        <button onClick={() => action(onApprove)} className="inline-flex items-center gap-2 rounded-button bg-aegis-green px-4 py-2 text-sm font-semibold text-aegis-bg"><Check className="h-4 w-4" /> Approve</button>
        <button onClick={() => onModify(approval.id)} className="ghost-button"><Edit3 className="h-4 w-4" /> Modify</button>
        <button onClick={() => action(onReject)} className="inline-flex items-center gap-2 rounded-button bg-aegis-red px-4 py-2 text-sm font-semibold text-white"><X className="h-4 w-4" /> Reject</button>
      </div>
    </div>
  );
}
