import { useCallback, useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { createPipeline as createPipelineRequest, listPipelines, resumePipeline } from "../lib/api.js";

function toViewModel(pipeline) {
  const startedAt = pipeline.started_at || pipeline.created_at;
  let started = "Not started";
  if (startedAt) {
    const date = new Date(startedAt);
    if (!Number.isNaN(date.getTime())) started = formatDistanceToNow(date, { addSuffix: true });
  }
  return {
    ...pipeline,
    id: pipeline.id,
    dataset: pipeline.dataset || pipeline.dataset_id || "Unknown dataset",
    status: pipeline.status || "pending",
    progress: Number.isFinite(pipeline.progress) ? pipeline.progress : 0,
    started,
    checkpoint: pipeline.checkpoint || {}
  };
}

export function usePipelines() {
  const [pipelines, setPipelines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPipelines();
      setPipelines(data.map(toViewModel));
      setError("");
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to load pipelines.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 15000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const createPipeline = useCallback(async (payload) => {
    setBusyId("create");
    try {
      await createPipelineRequest(payload);
      await refresh();
      return true;
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to start pipeline.");
      return false;
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const retry = useCallback(async (id) => {
    setBusyId(id);
    try {
      await resumePipeline(id);
      await refresh();
      return true;
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to resume pipeline.");
      return false;
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const getPipeline = useCallback((id) => pipelines.find((pipeline) => pipeline.id === id), [pipelines]);

  return { pipelines, loading, error, busyId, createPipeline, getPipeline, retry, refresh };
}
