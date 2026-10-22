import { BrainCircuit, Download, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { downloadModel } from "../lib/api.js";
import api from "../lib/api.js";
import { cn } from "../lib/utils.js";

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function Models() {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/models/");
      setModels(data.models || []);
      setError("");
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to load model registry.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const download = async (model) => {
    setBusyId(model.id);
    try {
      const blob = await downloadModel(model.id);
      saveBlob(blob, `${model.name.replace(/[^A-Za-z0-9._-]/g, "_")}.joblib`);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to download model artifact.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div><h2 className="text-xl font-bold text-white">Model registry</h2><p className="mt-1 text-sm text-aegis-muted">Trained models and evaluation metrics from datasets you can access.</p></div>
        <button type="button" onClick={refresh} disabled={loading} className="ghost-button inline-flex items-center gap-2 px-3 py-2"><RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} /> Refresh</button>
      </div>
      {error ? <div role="alert" className="rounded-button border border-aegis-red/30 bg-aegis-red/10 p-3 text-sm text-aegis-red">{error}</div> : null}
      {loading ? <div className="h-48 skeleton" /> : models.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {models.map((model) => (
            <article key={model.id} className="panel space-y-4 p-5">
              <div className="flex items-start gap-3">
                <div className="rounded-button border border-aegis-blue/20 bg-aegis-blue/10 p-2"><BrainCircuit className="h-5 w-5 text-aegis-blue" /></div>
                <div className="min-w-0 flex-1"><h3 className="break-words font-semibold text-white">{model.name}</h3><p className="mt-1 text-xs text-aegis-muted">{model.algorithm} · {model.problem_type || "unknown task"}</p><p className="mt-1 text-xs text-aegis-muted">Dataset: {model.dataset_name || model.dataset_id}</p></div>
                <span className="rounded-full bg-aegis-blue/10 px-2.5 py-1 text-xs capitalize text-aegis-blue">{model.status}</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(model.metrics || {}).map(([key, value]) => <div key={key} className="rounded-button border border-aegis-border bg-aegis-bg/60 p-3"><p className="text-xs text-aegis-muted">{key.replaceAll("_", " ")}</p><p className="mt-1 text-lg font-semibold text-white">{typeof value === "number" ? value.toFixed(4) : String(value)}</p></div>)}
              </div>
              <div className="flex items-center justify-between gap-3"><p className="text-xs text-aegis-muted">{model.created_at ? new Date(model.created_at).toLocaleString() : "Date unavailable"}</p><button type="button" disabled={!model.artifact_available || busyId === model.id} onClick={() => download(model)} className="ghost-button inline-flex items-center gap-2 px-3 py-2 disabled:opacity-50"><Download className="h-4 w-4" /> {busyId === model.id ? "Preparing…" : "Download artifact"}</button></div>
            </article>
          ))}
        </div>
      ) : <div className="panel flex min-h-[260px] flex-col items-center justify-center p-8 text-center"><BrainCircuit className="h-12 w-12 text-aegis-muted" /><h3 className="mt-3 text-lg font-semibold text-white">No trained models yet</h3><p className="mt-2 max-w-md text-sm text-aegis-muted">Train a baseline model by calling the ML agent with a dataset ID, target column, and task type. Models will appear here with held-out evaluation metrics.</p></div>}
    </div>
  );
}
