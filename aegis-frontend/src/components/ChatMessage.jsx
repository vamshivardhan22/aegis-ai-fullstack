import { Database } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "../lib/utils.js";

export default function ChatMessage({ message }) {
  const user = message.sender === "user";
  return (
    <div className={cn("flex", user ? "justify-end" : "justify-start")}>
      <div className={cn("max-w-[82%] rounded-card px-4 py-3 shadow-lg", user ? "rounded-br-sm bg-gradient-to-r from-aegis-blue to-aegis-purple text-white" : "rounded-bl-sm border border-aegis-border bg-aegis-card text-aegis-text")}>
        <p className="whitespace-pre-wrap text-sm leading-6">{message.text}</p>
        <div className={cn("mt-2 text-[11px]", user ? "text-white/75" : "text-aegis-muted")}>{formatDistanceToNow(message.time || new Date(), { addSuffix: true })}</div>
        {!user && message.sources?.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.sources.map((source) => (
              <span key={source} className="inline-flex items-center gap-1 rounded-full border border-aegis-blue/30 bg-aegis-blue/10 px-2 py-1 text-xs text-aegis-blue"><Database className="h-3 w-3" /> {source}</span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
