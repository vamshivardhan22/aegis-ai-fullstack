import { Play } from "lucide-react";
import { useState } from "react";
import UploadZone from "../components/UploadZone.jsx";
import { useToast } from "../components/Toast.jsx";

export default function Upload() {
  const [file, setFile] = useState(null);
  const [recent, setRecent] = useState(["claims_raw.xlsx", "customer_events.json", "transactions_q3.csv"]);
  const toast = useToast();
  const start = () => {
    if (!file) { toast.error("Choose a dataset before starting a pipeline."); return; }
    setRecent((current) => [file.name, ...current.slice(0, 4)]);
    toast.success("Pipeline started.");
  };
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <section>
        <UploadZone onUpload={setFile} />
        <button onClick={start} className="gradient-button mt-5"><Play className="h-4 w-4" /> Start Pipeline</button>
      </section>
      <aside className="panel p-5">
        <h2 className="text-lg font-bold text-white">Recent Uploads</h2>
        <div className="mt-4 space-y-3">{recent.map((name) => <div key={name} className="rounded-button border border-aegis-border bg-aegis-bg/60 px-3 py-2 text-sm text-aegis-text">{name}</div>)}</div>
      </aside>
    </div>
  );
}
