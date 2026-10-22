import { ShieldCheck, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { useToast } from "../components/Toast.jsx";
import api from "../lib/api.js";

function normalizeApproval(item) {
  const piiColumns = item.pii_columns || {};
  return {
    id: item.pipeline_id,
    title: `Pipeline ${item.pipeline_id?.slice(0, 8) || ""} · Approval required`,
    riskLevel: Object.keys(piiColumns).length ? "high" : "medium",
    description: item.error_message || (
      Object.keys(piiColumns).length
        ? "Sensitive columns were masked. Review the staged output before publishing."
        : "This pipeline paused at a configured governance gate."
    ),
    impact: JSON.stringify({
      project_id: item.project_id,
      dataset_id: item.dataset_id,
      current_state: item.current_state,
      quality_score: item.quality_score,
      pii_columns: piiColumns,
      candidate_artifact: item.candidate_artifact
    }, null, 2)
  };
}

function decisionPayload(decision, rationale) {
  return { decision, rationale };
}

export default function Approvals() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/approvals/pending");
      setItems((data.pipelines || []).map(normalizeApproval));
      setError("");
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to load pending approvals.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const decide = async (id, decision) => {
    setBusyId(id);
    try {
      const endpoint = decision === "approve" ? "approve" : "reject";
      await api.post(`/approvals/${encodeURIComponent(id)}/${endpoint}`, decisionPayload(
        decision,
        decision === "approve" ? "Approved from Aegis DataOps console." : "Rejected from Aegis DataOps console."
      ));
      toast.success(decision === "approve" ? "Output published successfully." : "Pipeline rejected; output was not published.");
      window.dispatchEvent(new CustomEvent("aegis-approvals-updated"));
      await refresh();
    } catch (err) {
      const message = err.response?.data?.detail || err.message || "Approval action failed.";
      setError(typeof message === "string" ? message : JSON.stringify(message));
      toast.error("Approval action failed.");
    } finally {
      setBusyId(null);
    }
  };

  if (loading && !items.length) return <div className="h-64 skeleton" />;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div><h2 className="text-xl font-bold text-white">Human approvals</h2><p className="mt-1 text-sm text-aegis-muted">Only persisted pending approvals are shown.</p></div>
        <button type="button" onClick={refresh} disabled={loading} className="ghost-button inline-flex items-center gap-2 px-3 py-2"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh</button>
      </div>
      {error ? <div role="alert" className="rounded-button border border-aegis-red/30 bg-aegis-red/10 p-3 text-sm text-aegis-red">{error}</div> : null}
      {!items.length && !loading ? <div className="panel flex min-h-[320px] flex-col items-center justify-center p-8 text-center"><ShieldCheck className="h-14 w-14 text-aegis-green" /><h2 className="mt-4 text-2xl font-bold text-white">No pending approvals</h2><p className="mt-2 text-aegis-muted">There are no approval checkpoints for projects you can access.</p></div> : null}
      <div className="grid gap-4 xl:grid-cols-2">
        {items.map((approval) => (
          <div key={approval.id} className={busyId === approval.id ? "pointer-events-none opacity-60" : ""}>
            <ApprovalCard approval={approval} onApprove={(id) => decide(id, "approve")} onReject={(id) => decide(id, "reject")} />
          </div>
        ))}
      </div>
    </div>
  );
}
