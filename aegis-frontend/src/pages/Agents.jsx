import AgentCard from "../components/AgentCard.jsx";
import { useToast } from "../components/Toast.jsx";
import { useAgents } from "../hooks/useAgents.js";

export default function Agents() {
  const { agents, loading, error, executeAgent } = useAgents();
  const toast = useToast();
  const execute = async (type) => {
    try {
      await executeAgent(type, { requested_by: "console" });
      toast.success(`${type} agent execution started.`);
    } catch (error) {
      if (error.response?.status === 403) return;
      toast.error("Agent execution failed.");
    }
  };
  return (
    <div className="space-y-4">
      {error ? <div className="rounded-button border border-aegis-orange/40 bg-aegis-orange/10 px-4 py-3 text-sm text-aegis-orange">Using cached agent data while API reconnects.</div> : null}
      {loading ? <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">{Array.from({ length: 6 }).map((_, index) => <div key={index} className="h-64 skeleton" />)}</div> : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">{agents.map((agent) => <AgentCard key={agent.type} agent={agent} onExecute={execute} />)}</div>
      )}
    </div>
  );
}
