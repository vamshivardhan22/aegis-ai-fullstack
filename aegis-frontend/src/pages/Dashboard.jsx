import { Activity, Bot, GitBranch, Gauge } from "lucide-react";
import MetricCard from "../components/MetricCard.jsx";
import PipelineTimeline from "../components/PipelineTimeline.jsx";

const steps = [
  { title: "Ingestion", status: "completed", meta: "Bronze landing complete" },
  { title: "Schema", status: "completed", meta: "42 columns mapped" },
  { title: "Quality", status: "completed", meta: "98.4% pass rate" },
  { title: "Features", status: "running", meta: "Encoding high-cardinality fields" },
  { title: "ML", status: "pending", meta: "Queued for trainer" },
  { title: "Deploy", status: "pending", meta: "Waiting for model artifact" }
];

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        <MetricCard label="Active Agents" value="8" delta="+3" color="blue" sparkline={[4, 5, 5, 6, 8]} />
        <MetricCard label="Pipelines Completed" value="1,247" delta="+89" color="green" sparkline={[900, 980, 1020, 1120, 1247]} />
        <MetricCard label="Success Rate" value="98.4%" delta="+0.3%" color="purple" sparkline={[96, 97, 98, 98.1, 98.4]} />
        <MetricCard label="Queue Depth" value="3" delta="-12" deltaType="down" color="orange" sparkline={[16, 14, 9, 7, 3]} />
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.1fr_.9fr]">
        <section className="panel p-6">
          <div className="mb-6 flex items-center gap-3"><GitBranch className="h-5 w-5 text-aegis-blue" /><h2 className="text-lg font-bold text-white">Pipeline Timeline</h2></div>
          <PipelineTimeline steps={steps} />
        </section>
        <section className="panel p-6">
          <div className="mb-6 flex items-center gap-3"><Activity className="h-5 w-5 text-aegis-green" /><h2 className="text-lg font-bold text-white">Recent Activity</h2></div>
          <div className="space-y-4">
            {[["Quality Guardian flagged 2 outlier clusters", Bot], ["Fraud Model Refresh entered feature stage", GitBranch], ["Latency stayed below 120ms p95", Gauge]].map(([text, Icon]) => (
              <div key={text} className="flex gap-3 rounded-button border border-aegis-border bg-aegis-bg/50 p-3">
                <Icon className="mt-0.5 h-4 w-4 text-aegis-blue" />
                <div><p className="text-sm text-white">{text}</p><p className="text-xs text-aegis-muted">2 minutes ago</p></div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
