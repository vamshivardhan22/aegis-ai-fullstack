import { useCallback, useEffect, useState } from "react";
import { addMinutes, formatDistanceToNow } from "date-fns";
import { pipelineSocket } from "../lib/websocket.js";

const statuses = ["running", "completed", "failed", "approval_required", "pending"];
const fallbackPipelines = Array.from({ length: 8 }, (_, index) => ({
  id: `PL-${142 - index}`,
  name: ["Fraud Model Refresh", "Revenue Mart Sync", "Churn Features", "Claims Enrichment"][index % 4],
  dataset: ["transactions_q3.csv", "revenue_gold.parquet", "customer_events.json", "claims_raw.xlsx"][index % 4],
  status: statuses[index % statuses.length],
  progress: [68, 100, 32, 88, 12][index % 5],
  started: formatDistanceToNow(addMinutes(new Date(), -18 - index * 14), { addSuffix: true })
}));

export function usePipelines() {
  const [pipelines, setPipelines] = useState(fallbackPipelines);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [wsStatus, setWsStatus] = useState("idle");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setPipelines(fallbackPipelines);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const url = `${import.meta.env.VITE_WS_URL || "ws://localhost:8000"}/ws/pipelines`;
    pipelineSocket.connect(url, (event) => {
      if (event?.id) setPipelines((current) => current.map((pipeline) => pipeline.id === event.id ? { ...pipeline, ...event } : pipeline));
    }, setWsStatus);
    return () => pipelineSocket.disconnect();
  }, []);

  const createPipeline = (pipeline) => setPipelines((current) => [{ ...pipeline, id: `PL-${Date.now()}`, status: "pending", progress: 0, started: "now" }, ...current]);
  const retry = (id) => setPipelines((current) => current.map((pipeline) => pipeline.id === id ? { ...pipeline, status: "running", progress: 18 } : pipeline));
  const getPipeline = (id) => pipelines.find((pipeline) => pipeline.id === id);

  return { pipelines, loading, error, wsStatus, createPipeline, getPipeline, retry, refresh };
}
