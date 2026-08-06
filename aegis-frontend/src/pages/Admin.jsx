import { useEffect, useState } from "react";
import api from "../lib/api.js";

const usersFallback = [{ email: "admin@aegis.ai", role: "admin", status: "active" }, { email: "operator@aegis.ai", role: "operator", status: "active" }];
const logsFallback = [{ action: "APPROVE_PIPELINE", user: "admin@aegis.ai", resource: "PL-142", time: "3m ago", before: { status: "approval_required" }, after: { status: "running" } }];

export default function Admin() {
  const [tab, setTab] = useState("users");
  const [users, setUsers] = useState(usersFallback);
  const [logs, setLogs] = useState(logsFallback);
  useEffect(() => {
    api.get("/admin/users").then(({ data }) => setUsers(Array.isArray(data) ? data : data.users || usersFallback)).catch(() => {});
    api.get("/admin/audit-logs").then(({ data }) => setLogs(Array.isArray(data) ? data : data.logs || logsFallback)).catch(() => {});
  }, []);
  return (
    <div className="space-y-5">
      <div className="flex gap-2">{["users", "audit", "settings"].map((item) => <button key={item} onClick={() => setTab(item)} className={`rounded-button px-4 py-2 text-sm font-semibold capitalize ${tab === item ? "bg-aegis-blue text-white" : "border border-aegis-border text-aegis-muted"}`}>{item}</button>)}</div>
      {tab === "users" ? <Table headers={["Email", "Role", "Status", "Actions"]} rows={users.map((user) => [user.email, user.role, user.status, "Disable"])} /> : null}
      {tab === "audit" ? (
        <div className="panel overflow-auto">
          <table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-aegis-bg/70 text-aegis-muted"><tr>{["Action", "User", "Resource", "Time", "Before/After"].map((h) => <th key={h} className="px-5 py-4">{h}</th>)}</tr></thead><tbody>{logs.map((log, index) => <tr key={index} className="border-t border-aegis-border"><td className="px-5 py-4 font-mono text-aegis-blue">{log.action}</td><td className="px-5 py-4 text-white">{log.user}</td><td className="px-5 py-4 text-aegis-muted">{log.resource}</td><td className="px-5 py-4 text-aegis-muted">{log.time}</td><td className="px-5 py-4"><pre className="rounded-button bg-aegis-bg p-3 text-xs text-aegis-muted">{JSON.stringify({ before: log.before, after: log.after }, null, 2)}</pre></td></tr>)}</tbody></table>
        </div>
      ) : null}
      {tab === "settings" ? <section className="panel max-w-xl p-5"><label className="block"><span className="mb-2 block text-sm text-aegis-muted">Audit retention days</span><input className="field" type="number" defaultValue="365" min="30" /></label><button className="gradient-button mt-4">Save Settings</button></section> : null}
    </div>
  );
}

function Table({ headers, rows }) {
  return <div className="panel overflow-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-aegis-bg/70 text-aegis-muted"><tr>{headers.map((h) => <th key={h} className="px-5 py-4">{h}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-aegis-border">{row.map((cell, cellIndex) => <td key={cellIndex} className="px-5 py-4 text-aegis-text">{cellIndex === 1 ? <span className="rounded-full bg-aegis-purple/10 px-2 py-1 text-xs text-aegis-purple">{cell}</span> : cellIndex === 3 ? <button className="ghost-button px-3 py-2">{cell}</button> : cell}</td>)}</tr>)}</tbody></table></div>;
}
