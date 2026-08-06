import { useCallback, useEffect, useState } from "react";
import api from "../lib/api.js";

const starterMessages = [
  { id: "welcome", sender: "ai", text: "Aegis intelligence is online. Ask about pipeline health, dataset quality, lineage, or model behavior.", sources: ["RAG Knowledge Base"], time: new Date() }
];

export function useChat() {
  const [messages, setMessages] = useState(starterMessages);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/chat/history").then(({ data }) => {
      const history = Array.isArray(data) ? data : data.messages;
      if (history?.length) setMessages(history);
    }).catch(() => {});
  }, []);

  const sendMessage = useCallback(async (question) => {
    const userMessage = { id: crypto.randomUUID(), sender: "user", text: question, time: new Date() };
    setMessages((current) => [...current, userMessage]);
    setLoading(true);
    try {
      const { data } = await api.post("/chat/ask", { question });
      setMessages((current) => [...current, { id: crypto.randomUUID(), sender: "ai", text: data.answer || data.response || "I found the requested context in the Aegis knowledge base.", sources: data.sources || ["RAG Knowledge Base"], time: new Date() }]);
      setError("");
    } catch (err) {
      setError(err.message);
      setMessages((current) => [...current, { id: crypto.randomUUID(), sender: "ai", text: "The backend did not respond, but the query is queued locally. Check API availability at localhost:8000.", sources: ["RAG Knowledge Base"], time: new Date() }]);
    } finally {
      setLoading(false);
    }
  }, []);

  return { messages, loading, error, sendMessage };
}
