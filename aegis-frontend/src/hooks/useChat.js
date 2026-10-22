import { useCallback, useEffect, useState } from "react";
import api from "../lib/api.js";

function sourceLabel(source) {
  if (typeof source === "string") return source;
  if (!source || typeof source !== "object") return "Source";
  return source.name || source.title || source.type || source.id || "Source";
}

function toMessages(turns) {
  return turns.flatMap((turn, index) => {
    const time = turn.created_at ? new Date(turn.created_at) : new Date();
    const response = turn.response || {};
    return [
      { id: `history-${index}-user-${turn.created_at || ""}`, sender: "user", text: turn.question, time },
      {
        id: `history-${index}-assistant-${turn.created_at || ""}`,
        sender: "ai",
        text: response.answer || response.response || "No answer text was returned.",
        sources: (response.sources || []).map(sourceLabel),
        time
      }
    ];
  });
}

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.get("/chat/history")
      .then(({ data }) => {
        if (active) setMessages(toMessages(Array.isArray(data.history) ? data.history : []));
      })
      .catch((err) => {
        if (active) setError(err.response?.data?.detail || err.message || "Unable to load chat history.");
      });
    return () => { active = false; };
  }, []);

  const sendMessage = useCallback(async (question) => {
    const userMessage = { id: crypto.randomUUID(), sender: "user", text: question, sources: [], time: new Date() };
    setMessages((current) => [...current, userMessage]);
    setLoading(true);
    setError("");
    try {
      const { data } = await api.post("/chat/ask", { question });
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        sender: "ai",
        text: data.answer || data.response || "The API returned no answer text.",
        sources: (data.sources || []).map(sourceLabel),
        time: new Date()
      }]);
    } catch (err) {
      const message = err.response?.data?.detail || err.message || "Chat request failed.";
      setError(typeof message === "string" ? message : JSON.stringify(message));
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        sender: "ai",
        text: "I could not complete that request. Check the error message above and retry when the API is available.",
        sources: [],
        time: new Date()
      }]);
    } finally {
      setLoading(false);
    }
  }, []);

  return { messages, loading, error, sendMessage };
}
