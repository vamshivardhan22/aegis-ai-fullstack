import { Play } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import UploadZone from "../components/UploadZone.jsx";
import { useToast } from "../components/Toast.jsx";
import { createPipeline, uploadDataset } from "../lib/api.js";

export default function Upload() {
  const [file, setFile] = useState(null);
  const [recent, setRecent] = useState(["claims_raw.xlsx", "customer_events.json", "transactions_q3.csv"]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  const start = async () => {
    if (!file) { toast.error("Choose a dataset before starting a pipeline."); return; }
    setLoading(true);
    try {
      const dataset = await uploadDataset(file);
      await createPipeline({ dataset_id: dataset.id, name: `${file.name} Pipeline` });
      setRecent((current) => [file.name, ...current.filter((name) => name !== file.name).slice(0, 4)]);
      toast.success("Pipeline started.");
      navigate("/pipelines");
    } catch (err) {
      toast.error(err.response?.data?.detail?.error || err.response?.data?.detail || "Pipeline start failed.");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <section>
        <UploadZone onUpload={setFile} />
        <button onClick={start} disabled={loading} className="gradient-button mt-5 disabled:cursor-not-allowed disabled:opacity-60"><Play className="h-4 w-4" /> {loading ? "Starting..." : "Start Pipeline"}</button>
      </section>
      <aside className="panel p-5">
        <h2 className="text-lg font-bold text-white">Recent Uploads</h2>
        <div className="mt-4 space-y-3">{recent.map((name) => <div key={name} className="rounded-button border border-aegis-border bg-aegis-bg/60 px-3 py-2 text-sm text-aegis-text">{name}</div>)}</div>
      </aside>
    </div>
  );
}
