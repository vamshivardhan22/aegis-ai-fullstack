import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "../lib/utils.js";

const ToastContext = createContext(null);

const icons = { success: CheckCircle2, error: XCircle, info: Info };
const tones = { success: "border-aegis-green text-aegis-green", error: "border-aegis-red text-aegis-red", info: "border-aegis-blue text-aegis-blue" };

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((type, message) => {
    const id = crypto.randomUUID();
    setItems((current) => [...current, { id, type, message }]);
    setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 3000);
  }, []);

  useEffect(() => {
    const handler = (event) => push(event.detail.type || "info", event.detail.message);
    window.addEventListener("aegis-toast", handler);
    return () => window.removeEventListener("aegis-toast", handler);
  }, [push]);

  const toast = useMemo(() => ({
    success: (message) => push("success", message),
    error: (message) => push("error", message),
    info: (message) => push("info", message)
  }), [push]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex w-[min(360px,calc(100vw-40px))] flex-col gap-3">
        {items.map((item) => {
          const Icon = icons[item.type] || Info;
          return (
            <div key={item.id} className={cn("panel flex items-start gap-3 px-4 py-3", tones[item.type])}>
              <Icon className="mt-0.5 h-5 w-5 shrink-0" />
              <p className="min-w-0 flex-1 text-sm text-aegis-text">{item.message}</p>
              <button className="rounded p-1 text-aegis-muted hover:text-white" onClick={() => setItems((current) => current.filter((next) => next.id !== item.id))} aria-label="Dismiss toast">
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
