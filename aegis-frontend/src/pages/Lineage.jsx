import { useState } from "react";
import LineageGraph from "../components/LineageGraph.jsx";

const graphs = {
  transactions: {
    nodes: [
      { id: "bronze", name: "raw_transactions", layer: "Bronze", x: 16, y: 52 },
      { id: "silver", name: "clean_transactions", layer: "Silver", x: 40, y: 28 },
      { id: "gold", name: "fraud_features", layer: "Gold", x: 64, y: 52 },
      { id: "model", name: "fraud_score_v4", layer: "Model", x: 86, y: 36 }
    ],
    edges: [{ source: "bronze", target: "silver" }, { source: "silver", target: "gold" }, { source: "gold", target: "model" }]
  },
  customers: {
    nodes: [
      { id: "bronze", name: "raw_customers", layer: "Bronze", x: 18, y: 35 },
      { id: "silver", name: "identity_resolved", layer: "Silver", x: 42, y: 58 },
      { id: "gold", name: "customer_360", layer: "Gold", x: 66, y: 36 },
      { id: "model", name: "churn_model_v2", layer: "Model", x: 84, y: 64 }
    ],
    edges: [{ source: "bronze", target: "silver" }, { source: "silver", target: "gold" }, { source: "gold", target: "model" }]
  }
};

export default function Lineage() {
  const [dataset, setDataset] = useState("transactions");
  const graph = graphs[dataset];
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <section className="panel p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-white">Dataset Lineage</h2>
          <select className="field w-64" value={dataset} onChange={(event) => setDataset(event.target.value)}>
            <option value="transactions">transactions_q3</option>
            <option value="customers">customer_360</option>
          </select>
        </div>
        <LineageGraph nodes={graph.nodes} edges={graph.edges} />
      </section>
      <aside className="panel p-5">
        <h3 className="text-lg font-bold text-white">Impact Analysis</h3>
        <div className="mt-4 space-y-3">
          {["2 downstream feature tables", "1 production model", "4 dashboard measures", "Approval gate required on schema drift"].map((item) => <div key={item} className="rounded-button border border-aegis-border bg-aegis-bg/60 p-3 text-sm text-aegis-text">{item}</div>)}
        </div>
      </aside>
    </div>
  );
}
