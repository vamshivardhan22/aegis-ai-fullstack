import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { useToast } from "../components/Toast.jsx";
import api from "../lib/api.js";

const fallback = [
  { id: "142", title: "Pipeline #142 - High Data Loss Risk", riskLevel: "high", description: "Quality agent detected a 17.8% null-rate increase in revenue_amount.", impact: "{\n  \"dataset\": \"transactions_q3\",\n  \"loss_risk\": \"17.8%\",\n  \"affected_models\": [\"fraud_score_v4\", \"ltv_v2\"],\n  \"recommendation\": \"pause deploy and run imputation branch\"\n}" },
  { id: "138", title: "Pipeline #138 - Schema Drift", riskLevel: "medium", description: "New enum values appeared in customer_segment.", impact: "{\n  \"new_values\": [\"enterprise_plus\", \"trial_revive\"],\n  \"downstream\": \"feature_encoder\",\n  \"alternative\": \"map unknowns to review bucket\"\n}" }
];

function normalizeApproval(item) {
  if (item.id) return item;
  const checkpoint = item.checkpoint || item.current_state || {};
  return {
    id: item.pipeline_id,
    title: `Pipeline ${item.pipeline_id} - Approval Required`,
    riskLevel: checkpoint.risk_level || "medium",
    description: item.error_message || "Pipeline is paused at a human governance gate.",
    impact: JSON.stringify({
      project_id: item.project_id,
      dataset_id: item.dataset_id,
      current_state: item.current_state,
      checkpoint: item.checkpoint
    }, null, 2)
  };
}

function decisionPayload(decision, rationale) {
  return {
    decision,
    rationale,
    modifications: {},
    alternative_action: null
  };
}

export default function Approvals() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  useEffect(() => {
    api.get("/approvals/pending").then(({ data }) => {
      const approvals = Array.isArray(data) ? data : data.approvals || data.pipelines;
      setItems((approvals || []).map(normalizeApproval));
    }).catch(() => {
      setItems(fallback.map((item) => ({ ...item, localOnly: true })));
      toast.info("Using local demo approvals while the approval API is unavailable.");
    }).finally(() => setLoading(false));
  }, []);
  const approve = async (id) => {
    const item = items.find((approval) => approval.id === id);
    if (!item?.localOnly) await api.post(`/approvals/${id}/approve`, decisionPayload("approve", "Approved from Aegis AI console."));
    setItems((current) => current.filter((item) => item.id !== id));
    window.dispatchEvent(new CustomEvent("aegis-approvals-updated"));
    toast.success("Approval accepted.");
  };
  const reject = async (id) => {
    const item = items.find((approval) => approval.id === id);
    if (!item?.localOnly) await api.post(`/approvals/${id}/reject`, decisionPayload("reject", "Rejected from Aegis AI console."));
    setItems((current) => current.filter((item) => item.id !== id));
    window.dispatchEvent(new CustomEvent("aegis-approvals-updated"));
    toast.error("Approval rejected.");
  };
  const modify = () => toast.info("Modification request opened for review.");
  if (loading) return <div className="h-64 skeleton" />;
  if (!items.length) return <div className="panel flex min-h-[420px] flex-col items-center justify-center p-8 text-center"><ShieldCheck className="h-14 w-14 text-aegis-green" /><h2 className="mt-4 text-2xl font-bold text-white">No pending approvals</h2><p className="mt-2 text-aegis-muted">Risk gates are clear.</p></div>;
  return <div className="grid gap-4 xl:grid-cols-2">{items.map((approval) => <ApprovalCard key={approval.id} approval={approval} onApprove={approve} onReject={reject} onModify={modify} />)}</div>;
}
