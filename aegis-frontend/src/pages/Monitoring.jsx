import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import MetricCard from "../components/MetricCard.jsx";

const chart = Array.from({ length: 24 }, (_, hour) => ({ hour: `${hour}:00`, latency: 70 + Math.round(Math.sin(hour / 2) * 18 + hour % 5), volume: 800 + hour * 28 + (hour % 4) * 90, execution: 18 + (hour % 6) * 7 }));
const alerts = [
  ["warning", "queue_depth", "10", "12", "4m ago"],
  ["critical", "null_rate", "5%", "17.8%", "9m ago"],
  ["info", "p95_latency", "150ms", "121ms", "15m ago"]
];

export default function Monitoring() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        <MetricCard label="API Latency" value="121ms" delta="-18ms" deltaType="down" color="green" />
        <MetricCard label="Request Volume" value="42.8k" delta="+8.1%" color="blue" />
        <MetricCard label="Agent Runtime" value="31s" delta="-4s" deltaType="down" color="purple" />
        <MetricCard label="Open Alerts" value="3" delta="+1" color="orange" />
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        <ChartPanel title="Latency 24h"><LineChart data={chart}><CartesianGrid stroke="#2d3a4f" /><XAxis dataKey="hour" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#1a2234", border: "1px solid #2d3a4f" }} /><Line dataKey="latency" stroke="#3b82f6" strokeWidth={2} dot={false} /></LineChart></ChartPanel>
        <ChartPanel title="Request Volume"><AreaChart data={chart}><CartesianGrid stroke="#2d3a4f" /><XAxis dataKey="hour" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#1a2234", border: "1px solid #2d3a4f" }} /><Area dataKey="volume" stroke="#22c55e" fill="#22c55e33" /></AreaChart></ChartPanel>
        <ChartPanel title="Agent Execution"><BarChart data={chart.slice(0, 8)}><CartesianGrid stroke="#2d3a4f" /><XAxis dataKey="hour" stroke="#94a3b8" /><YAxis stroke="#94a3b8" /><Tooltip contentStyle={{ background: "#1a2234", border: "1px solid #2d3a4f" }} /><Bar dataKey="execution" fill="#a855f7" radius={[6, 6, 0, 0]} /></BarChart></ChartPanel>
      </div>
      <section className="panel overflow-hidden">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-aegis-bg/70 text-aegis-muted"><tr>{["Severity", "Metric", "Threshold", "Actual", "Time", "Ack"].map((h) => <th key={h} className="px-5 py-4">{h}</th>)}</tr></thead>
          <tbody>{alerts.map(([severity, metric, threshold, actual, time]) => <tr key={metric} className="border-t border-aegis-border"><td className="px-5 py-4"><span className={`inline-block h-2.5 w-2.5 rounded-full ${severity === "critical" ? "bg-aegis-red" : severity === "warning" ? "bg-aegis-orange" : "bg-aegis-blue"}`} /> <span className="ml-2 capitalize">{severity}</span></td><td className="px-5 py-4 font-mono text-white">{metric}</td><td className="px-5 py-4 text-aegis-muted">{threshold}</td><td className="px-5 py-4 text-aegis-text">{actual}</td><td className="px-5 py-4 text-aegis-muted">{time}</td><td className="px-5 py-4"><button className="ghost-button px-3 py-2">Ack</button></td></tr>)}</tbody>
        </table>
      </section>
    </div>
  );
}

function ChartPanel({ title, children }) {
  return <section className="panel p-5"><h2 className="mb-4 text-lg font-bold text-white">{title}</h2><div className="h-72"><ResponsiveContainer>{children}</ResponsiveContainer></div></section>;
}
