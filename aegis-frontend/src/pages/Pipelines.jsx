import { Fragment, useEffect, useState } from "react";
import { RotateCcw, Play, RefreshCw } from "lucide-react";
import PipelineTimeline from "../components/PipelineTimeline.jsx";
import { usePipelines } from "../hooks/usePipelines.js";
import { listDatasets } from "../lib/api.js";
import { cn } from "../lib/utils.js";

const tabs = ["All", "Running", "Completed", "Failed", "Pending Approval"];
const badgeTone = {
  running: "bg-aegis-green/10 text-aegis-green",
  completed: "bg-aegis-green/10 text-aegis-green",
  failed: "bg-aegis-red/10 text-aegis-red",
  pending: "bg-aegis-blue/10 text-aegis-blue",
  approval_required: "bg-aegis-orange/10 text-aegis-orange",
  paused: "bg-aegis-orange/10 text-aegis-orange"
};

function timelineFor(pipeline) {
  const checkpoint = pipeline.checkpoint || {};
  const failed = pipeline.status === "failed";
  const approval = pipeline.status === "approval_required";
  const decision = checkpoint.human_decisions?.latest?.decision;
  return [
    { title: "CSV ingestion", status: checkpoint.source_sha256 ? "completed" : failed ? "failed" : "pending", meta: checkpoint.source_sha256 ? "Source checksum recorded" : pipeline.current_state || "Waiting" },
    { title: "Schema and quality profile", status: checkpoint.profile ? "completed" : failed ? "failed" : "pending", meta: checkpoint.profile ? `${checkpoint.profile.row_count} rows · ${checkpoint.profile.column_count} columns` : "Not completed" },
    { title: "PII policy and transformation", status: checkpoint.candidate_artifact ? "completed" : failed ? "failed" : "pending", meta: checkpoint.pii_columns ? `${Object.keys(checkpoint.pii_columns).length} sensitive columns detected` : "Not completed" },
    { title: "Human approval", status: approval ? "running" : decision === "approved" ? "completed" : decision === "rejected" ? "failed" : "pending", meta: approval ? "Output staged; approval required" : decision ? `Decision: ${decision}` : "No approval required yet" },
    { title: "Publish output", status: pipeline.status === "completed" ? "completed" : failed ? "failed" : "pending", meta: pipeline.status === "completed" ? `Output dataset: ${checkpoint.output_dataset_id || "published"}` : pipeline.error_message || "Not published" }
  ];
}

export default function Pipelines() {
  const { pipelines, loading, error, busyId, retry, refresh, createPipeline } = usePipelines();
  const [filter, setFilter] = useState("All");
  const [open, setOpen] = useState(null);
  const [datasets, setDatasets] = useState([]);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [datasetError, setDatasetError] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    listDatasets()
      .then((items) => { setDatasets(items.filter((item) => item.has_bronze_artifact)); setDatasetError(""); })
      .catch((err) => setDatasetError(err.response?.data?.detail || err.message || "Unable to load datasets."));
  }, []);

  const filtered = pipelines.filter((pipeline) => {
    if (filter === "All") return true;
    if (filter === "Pending Approval") return pipeline.status === "approval_required";
    return pipeline.status.replace("_", " ").toLowerCase() === filter.toLowerCase();
  });

  const startPipeline = async () => {
    if (!selectedDataset) return;
    setCreating(true);
    const ok = await createPipeline({ dataset_id: selectedDataset });
    if (ok) setSelectedDataset("");
    setCreating(false);
  };

  return (
    <div className="space-y-5">
      <section className="panel space-y-4 p-5">
        <div>
          <h2 className="text-lg font-semibold text-white">Run a governed CSV workflow</h2>
          <p className="mt-1 text-sm text-aegis-muted">Select an uploaded dataset. Sensitive columns are masked and the output waits for approval before publication.</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <select
            aria-label="Dataset to process"
            value={selectedDataset}
            onChange={(event) => setSelectedDataset(event.target.value)}
            className="min-w-0 flex-1 rounded-button border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
          >
            <option value="">Select a dataset with a CSV artifact</option>
            {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.row_count ?? "?"} rows</option>)}
          </select>
          <button
            type="button"
            disabled={!selectedDataset || creating || busyId !== null}
            onClick={startPipeline}
            className="primary-button inline-flex items-center justify-center gap-2 px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {creating ? "Starting…" : "Start pipeline"}
          </button>
          <button type="button" onClick={refresh} disabled={loading} className="ghost-button inline-flex items-center justify-center gap-2 px-3 py-2">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} /> Refresh
          </button>
        </div>
        {datasetError ? <p role="alert" className="text-sm text-aegis-red">{datasetError}</p> : null}
      </section>

      {error ? <div role="alert" className="rounded-button border border-aegis-red/30 bg-aegis-red/10 p-3 text-sm text-aegis-red">{error}</div> : null}

      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => <button key={tab} onClick={() => setFilter(tab)} className={cn("rounded-button px-4 py-2 text-sm font-semibold transition", filter === tab ? "bg-aegis-blue text-white" : "border border-aegis-border text-aegis-muted hover:text-white")}>{tab}</button>)}
      </div>

      <div className="panel overflow-hidden">
        {loading ? <div className="m-5 h-64 skeleton" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-aegis-bg/70 text-aegis-muted"><tr>{["ID", "Name", "Dataset", "Status", "Progress", "Started", "Actions"].map((h) => <th key={h} className="px-5 py-4 font-semibold">{h}</th>)}</tr></thead>
              <tbody>
                {filtered.map((pipeline) => (
                  <Fragment key={pipeline.id}>
                    <tr onClick={() => setOpen(open === pipeline.id ? null : pipeline.id)} className="cursor-pointer border-t border-aegis-border hover:bg-aegis-bg/40">
                      <td className="px-5 py-4 font-mono text-aegis-blue">{pipeline.id.slice(0, 8)}</td>
                      <td className="px-5 py-4 font-semibold text-white">{pipeline.name}</td>
                      <td className="px-5 py-4 text-aegis-muted">{pipeline.dataset}</td>
                      <td className="px-5 py-4"><span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold capitalize", badgeTone[pipeline.status] || "bg-aegis-bg text-aegis-muted")}>{pipeline.status.replace("_", " ")}</span></td>
                      <td className="px-5 py-4"><div className="h-2 w-32 rounded-full bg-aegis-bg"><div className="h-2 rounded-full bg-aegis-blue" style={{ width: `${pipeline.progress}%` }} /></div><span className="mt-1 block text-xs text-aegis-muted">{pipeline.progress}%</span></td>
                      <td className="px-5 py-4 text-aegis-muted">{pipeline.started}</td>
                      <td className="px-5 py-4">
                        {["failed", "pending", "running"].includes(pipeline.status) ? (
                          <button aria-label="Resume pipeline" disabled={busyId === pipeline.id} onClick={(event) => { event.stopPropagation(); retry(pipeline.id); }} className="ghost-button px-3 py-2 disabled:opacity-50">
                            <RotateCcw className={cn("h-4 w-4", busyId === pipeline.id && "animate-spin")} />
                          </button>
                        ) : pipeline.status === "approval_required" ? <span className="text-xs text-aegis-orange">Approval needed</span> : <span className="text-xs text-aegis-muted">—</span>}
                      </td>
                    </tr>
                    {open === pipeline.id ? <tr><td colSpan="7" className="border-t border-aegis-border bg-aegis-bg/35 px-8 py-5"><PipelineTimeline steps={timelineFor(pipeline)} /></td></tr> : null}
                  </Fragment>
                ))}
                {filtered.length === 0 && !loading ? <tr><td colSpan="7" className="px-5 py-12 text-center text-aegis-muted">{pipelines.length ? "No pipelines match this filter." : "No pipelines yet. Select a dataset above to start your first run."}</td></tr> : null}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
