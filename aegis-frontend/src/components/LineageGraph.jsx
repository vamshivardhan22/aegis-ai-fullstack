import { useState } from "react";
import { cn } from "../lib/utils.js";

const layerTone = { Bronze: "border-aegis-red text-aegis-red", Silver: "border-aegis-blue text-aegis-blue", Gold: "border-aegis-orange text-aegis-orange", Model: "border-aegis-purple text-aegis-purple" };

export default function LineageGraph({ nodes, edges }) {
  const [hovered, setHovered] = useState(null);
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  return (
    <div className="relative min-h-[430px] overflow-hidden rounded-card border border-aegis-border bg-aegis-bg/50">
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        <defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8" /></marker></defs>
        {edges.map((edge) => {
          const from = byId[edge.source];
          const to = byId[edge.target];
          if (!from || !to) return null;
          return <line key={`${edge.source}-${edge.target}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="#94a3b8" strokeWidth="0.35" markerEnd="url(#arrow)" opacity="0.75" />;
        })}
      </svg>
      {nodes.map((node) => (
        <button key={node.id} onMouseEnter={() => setHovered(node)} onMouseLeave={() => setHovered(null)} className={cn("absolute w-36 -translate-x-1/2 -translate-y-1/2 rounded-card border bg-aegis-card px-4 py-3 text-left shadow-xl transition hover:scale-105 hover:shadow-glow", layerTone[node.layer])} style={{ left: `${node.x}%`, top: `${node.y}%` }}>
          <span className="block text-[11px] font-bold uppercase tracking-[0.15em]">{node.layer}</span>
          <span className="mt-1 block text-sm font-semibold text-white">{node.name}</span>
        </button>
      ))}
      {hovered ? <div className="absolute bottom-4 left-4 rounded-button border border-aegis-border bg-aegis-card px-3 py-2 text-sm text-aegis-muted">{hovered.name} feeds downstream model and reporting assets.</div> : null}
    </div>
  );
}
