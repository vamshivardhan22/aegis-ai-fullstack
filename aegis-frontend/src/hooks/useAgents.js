import { useCallback, useEffect, useState } from "react";
import api from "../lib/api.js";

const fallbackAgents = [
  { name: "Ingestion Sentinel", type: "ingestion", status: "running", tasks: 342, success: 339, failed: 3, progress: 72 },
  { name: "Schema Mapper", type: "schema", status: "idle", tasks: 218, success: 216, failed: 2 },
  { name: "Quality Guardian", type: "quality", status: "running", tasks: 411, success: 407, failed: 4, progress: 48 },
  { name: "Feature Smith", type: "features", status: "idle", tasks: 187, success: 185, failed: 2 },
  { name: "Model Runner", type: "ml", status: "running", tasks: 96, success: 95, failed: 1, progress: 81 },
  { name: "Deployment Watch", type: "deploy", status: "idle", tasks: 72, success: 72, failed: 0 }
];

export function useAgents() {
  const [agents, setAgents] = useState(fallbackAgents);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/agents/");
      setAgents(Array.isArray(data) ? data : data.agents || fallbackAgents);
      setError("");
    } catch (err) {
      setError(err.message);
      setAgents(fallbackAgents);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  const executeAgent = async (type, context = {}) => {
    const { data } = await api.post(`/agents/${type}/execute`, context);
    await refresh();
    return data;
  };

  return { agents, loading, error, refresh, executeAgent };
}
