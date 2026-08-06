import { ChevronDown, RotateCcw } from "lucide-react";
import { useState } from "react";
import PipelineTimeline from "../components/PipelineTimeline.jsx";
import { usePipelines } from "../hooks/usePipelines.js";
import { cn } from "../lib/utils.js";

const tabs = ["All", "Running", "Completed", "Failed", "Pending Approval"];
const badgeTone = { running: "bg-aegis-green/10 text-aegis-green", completed: "bg-aegis-green/10 text-aegis-green", failed: "bg-aegis-red/10 text-aegis-red", pending: "bg-aegis-blue/10 text-aegis-blue", approval_required: "bg-aegis-orange/10 text-aegis-orange" };

export default function Pipelines() {
  const { pipelines, loading, retry } = usePipelines();
  const [filter, setFilter] = useState("All");
  const [open, setOpen] = useState(null);
  const filtered = pipelines.filter((pipeline) => filter === "All" || pipeline.status.replace("_", " ").toLowerCase().includes(filter.replace("Pending Approval", "approval required").toLowerCase()));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">{tabs.map((tab) => <button key={tab} onClick={() => setFilter(tab)} className={cn("rounded-button px-4 py-2 text-sm font-semibold transition", filter === tab ? "bg-aegis-blue text-white" : "border border-aegis-border text-aegis-muted hover:text-white")}>{tab}</button>)}</div>
      <div className="panel overflow-hidden">
        {loading ? <div className="m-5 h-64 skeleton" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-aegis-bg/70 text-aegis-muted"><tr>{["ID", "Name", "Dataset", "Status", "Progress", "Started", "Actions"].map((h) => <th key={h} className="px-5 py-4 font-semibold">{h}</th>)}</tr></thead>
              <tbody>
                {filtered.map((pipeline) => (
                  <>
                    <tr key={pipeline.id} onClick={() => setOpen(open === pipeline.id ? null : pipeline.id)} className="cursor-pointer border-t border-aegis-border hover:bg-aegis-bg/40">
                      <td className="px-5 py-4 font-mono text-aegis-blue">{pipeline.id}</td>
                      <td className="px-5 py-4 font-semibold text-white">{pipeline.name}</td>
                      <td className="px-5 py-4 text-aegis-muted">{pipeline.dataset}</td>
                      <td className="px-5 py-4"><span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold capitalize", badgeTone[pipeline.status])}>{pipeline.status.replace("_", " ")}</span></td>
                      <td className="px-5 py-4"><div className="h-2 w-32 rounded-full bg-aegis-bg"><div className="h-2 rounded-full bg-aegis-blue" style={{ width: `${pipeline.progress}%` }} /></div></td>
                      <td className="px-5 py-4 text-aegis-muted">{pipeline.started}</td>
                      <td className="px-5 py-4"><button onClick={(event) => { event.stopPropagation(); retry(pipeline.id); }} className="ghost-button px-3 py-2"><RotateCcw className="h-4 w-4" /></button></td>
                    </tr>
                    {open === pipeline.id ? <tr><td colSpan="7" className="border-t border-aegis-border bg-aegis-bg/35 px-8 py-5"><PipelineTimeline steps={[{ title: "Ingestion", status: "completed" }, { title: "Quality", status: pipeline.status === "failed" ? "failed" : "completed" }, { title: "Approval", status: pipeline.status === "approval_required" ? "running" : "pending" }]} /></td></tr> : null}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
