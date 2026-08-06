import { Send } from "lucide-react";
import { useRef, useState } from "react";
import ChatMessage from "../components/ChatMessage.jsx";
import { useChat } from "../hooks/useChat.js";

const prompts = ["Why did pipeline 14 fail?", "Show datasets with missing values", "What is model accuracy?"];

export default function Chat() {
  const { messages, loading, sendMessage } = useChat();
  const [text, setText] = useState("");
  const inputRef = useRef(null);
  const submit = async (event) => {
    event.preventDefault();
    if (!text.trim()) return;
    const question = text.trim();
    setText("");
    await sendMessage(question);
  };
  return (
    <div className="flex h-[calc(100vh-132px)] min-h-[620px] flex-col overflow-hidden rounded-card border border-aegis-border bg-aegis-bg/50">
      <div className="flex-1 space-y-4 overflow-y-auto p-4 md:p-6">
        {messages.map((message) => <ChatMessage key={message.id} message={message} />)}
        {loading ? <div className="flex gap-1 px-4"><span className="h-2 w-2 animate-bounce rounded-full bg-aegis-blue" /><span className="h-2 w-2 animate-bounce rounded-full bg-aegis-blue [animation-delay:120ms]" /><span className="h-2 w-2 animate-bounce rounded-full bg-aegis-blue [animation-delay:240ms]" /></div> : null}
      </div>
      <div className="border-t border-aegis-border bg-aegis-card/70 p-4">
        <div className="mb-3 flex flex-wrap gap-2">{prompts.map((prompt) => <button key={prompt} onClick={() => { setText(prompt); inputRef.current?.focus(); }} className="rounded-full border border-aegis-border px-3 py-1.5 text-xs text-aegis-muted hover:border-aegis-blue hover:text-white">{prompt}</button>)}</div>
        <form onSubmit={submit} className="flex gap-3">
          <input ref={inputRef} className="field" value={text} onChange={(event) => setText(event.target.value)} placeholder="Ask Aegis about pipelines, datasets, models, or risks..." />
          <button className="gradient-button px-4" disabled={loading}><Send className="h-4 w-4" /></button>
        </form>
      </div>
    </div>
  );
}
