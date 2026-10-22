import { Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import UploadZone from "../components/UploadZone.jsx";
import { useToast } from "../components/Toast.jsx";
import { createPipeline, listDatasets, uploadDataset } from "../lib/api.js";

export default function Upload() {
  const [file, setFile] = useState(null);
  const [uploadKey, setUploadKey] = useState(0);
  const [recent, setRecent] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [error, setError] = useState("");
  const toast = useToast();

  const refreshRecent = useCallback(async () => {
    setLoadingRecent(true);
    try {
      setRecent(await listDatasets());
      setError("");
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to load datasets.");
    } finally {
      setLoadingRecent(false);
    }
  }, []);

  useEffect(() => { refreshRecent(); }, [refreshRecent]);

  const start = async () => {
    if (!file) {
      toast.error("Choose a CSV file before starting a pipeline.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const dataset = await uploadDataset(file);
      setRecent((current) => [dataset, ...current.filter((item) => item.id !== dataset.id)]);
      const result = await createPipeline({ dataset_id: dataset.id });
      const status = result.pipeline?.status || result.execution?.status;
      if (status === "approval_required") {
        toast.info("CSV processed and sensitive fields masked. Human approval is required before publication.");
      } else if (status === "completed") {
        toast.success("CSV pipeline completed and output was published.");
      } else {
        const message = result.pipeline?.error_message || "Pipeline did not complete.";
        setError(message);
        toast.error("Pipeline failed. Review the error before retrying.");
      }
      setFile(null);
      await refreshRecent();
    } catch (err) {
      const message = err.response?.data?.detail || err.message || "Upload or pipeline execution failed.";
      setError(typeof message === "string" ? message : JSON.stringify(message));
      toast.error("Upload or pipeline execution failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <section>
        <UploadZone key={uploadKey} onUpload={setFile} />
        <button type="button" disabled={!file || busy} onClick={start} className="gradient-button mt-5 disabled:cursor-not-allowed disabled:opacity-50">
          <Play className="h-4 w-4" /> {busy ? "Uploading and processing…" : "Upload and Start Pipeline"}
        </button>
        <p className="mt-3 text-sm text-aegis-muted">The first workflow accepts CSV files up to 10 MiB. Sensitive fields are masked before staging; sensitive output requires approval before publication.</p>
        {error ? <div role="alert" className="mt-4 rounded-button border border-aegis-red/30 bg-aegis-red/10 p-3 text-sm text-aegis-red">{error}</div> : null}
      </section>
      <aside className="panel p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-white">Your datasets</h2>
          <button type="button" onClick={refreshRecent} disabled={loadingRecent} aria-label="Refresh datasets" className="ghost-button p-2"><RefreshCw className={`h-4 w-4 ${loadingRecent ? "animate-spin" : ""}`} /></button>
        </div>
        {loadingRecent ? <div className="mt-4 h-24 skeleton" /> : recent.length ? (
          <div className="mt-4 space-y-3">
            {recent.slice(0, 10).map((dataset) => (
              <div key={dataset.id} className="rounded-button border border-aegis-border bg-aegis-bg/60 px-3 py-3">
                <p className="break-all text-sm font-medium text-aegis-text">{dataset.name}</p>
                <p className="mt-1 text-xs text-aegis-muted">{dataset.row_count ?? "Unknown"} rows · {dataset.column_count ?? "Unknown"} columns</p>
              </div>
            ))}
          </div>
        ) : <p className="mt-4 text-sm text-aegis-muted">No datasets uploaded yet.</p>}
      </aside>
    </div>
  );
}
