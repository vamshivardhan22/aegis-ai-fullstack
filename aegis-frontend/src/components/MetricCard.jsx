import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { cn } from "../lib/utils.js";

const colorMap = { blue: "#3b82f6", green: "#22c55e", purple: "#a855f7", orange: "#f59e0b", red: "#ef4444" };

export default function MetricCard({ label, value, delta, deltaType = "up", color = "blue", sparkline = [] }) {
  const positive = deltaType === "up";
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  const chartData = sparkline.map((v, index) => ({ index, value: v }));
  return (
    <div className="panel overflow-hidden">
      <div className="h-[3px]" style={{ background: colorMap[color] || colorMap.blue }} />
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-aegis-muted">{label}</p>
            <p className="mt-2 text-3xl font-bold text-white">{value}</p>
          </div>
          {chartData.length ? (
            <div className="h-12 w-24">
              <ResponsiveContainer>
                <LineChart data={chartData}>
                  <Line type="monotone" dataKey="value" stroke={colorMap[color]} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </div>
        <div className={cn("mt-4 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold", positive ? "bg-aegis-green/10 text-aegis-green" : "bg-aegis-red/10 text-aegis-red")}>
          <Icon className="h-3.5 w-3.5" /> {delta}
        </div>
      </div>
    </div>
  );
}
