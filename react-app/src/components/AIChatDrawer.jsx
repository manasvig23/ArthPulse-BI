import { useState, useRef, useEffect } from "react";
import { API_BASE, getToken } from "../api.js";
import { Icon } from "./Kpi.jsx";

export default function AIChatDrawer({ onClose, period }) {
  const [messages, setMessages] = useState([
    { sender: "ai", text: `Hello! I'm your ArthPulse AI Assistant. I am grounded in your ${period} financial records. Ask me anything about sales, inventory, or cash flow!` }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatBottomRef = useRef(null);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMsg = input.trim();
    setInput("");
    setMessages(prev => [...prev, { sender: "user", text: userMsg }]);
    setLoading(true);

    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/ai/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify({ question: userMsg, period })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to fetch response");

      setMessages(prev => [...prev, { sender: "ai", text: data.answer }]);
    } catch (err) {
      setMessages(prev => [...prev, { sender: "ai", text: `Error: ${err.message}. Make sure your FastAPI backend is running and GEMINI_API_KEY is configured.` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal ai-chat-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: "520px", height: "600px", display: "flex", flexDirection: "column", padding: 0 }}>
        
        {/* Chat Header */}
        <div style={{ padding: "18px 22px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", justifyContent: "space-between", background: "var(--soft)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ display: "grid", placeItems: "center", width: "32px", height: "32px", borderRadius: "50%", background: "var(--green)", color: "#fff" }}>
              <Icon name="spark" size={16} />
            </span>
            <div>
              <h3 style={{ fontSize: "16px", margin: 0 }}>Arth AI Assistant</h3>
              <small style={{ color: "var(--muted)", fontSize: "11px" }}>Grounded in live Tally-synced dataset ({period})</small>
            </div>
          </div>
          <button className="secondary-button" onClick={onClose} style={{ padding: "6px 10px", fontSize: "12px" }}>✕ Close</button>
        </div>

        {/* Chat Messages Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: "14px" }}>
          {messages.map((m, idx) => (
            <div key={idx} style={{
              alignSelf: m.sender === "user" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              padding: "12px 16px",
              borderRadius: m.sender === "user" ? "16px 16px 2px 16px" : "16px 16px 16px 2px",
              background: m.sender === "user" ? "var(--green)" : "var(--soft)",
              color: m.sender === "user" ? "#fff" : "var(--ink)",
              fontSize: "13.5px",
              lineHeight: "1.5",
              boxShadow: "var(--shadow)"
            }}>
              {m.text}
            </div>
          ))}
          {loading && (
            <div style={{ alignSelf: "flex-start", padding: "12px 16px", borderRadius: "16px", background: "var(--soft)", color: "var(--muted)", fontSize: "13px" }}>
              Analyzing data and formulating grounded response…
            </div>
          )}
          <div ref={chatBottomRef} />
        </div>

        {/* Chat Input Footer */}
        <form onSubmit={sendMessage} style={{ padding: "16px 20px", borderTop: "1px solid var(--line)", display: "flex", gap: "10px", background: "var(--card)" }}>
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask e.g. 'Why did sales reduce this month?'"
            style={{ flex: 1, padding: "11px 14px", border: "1px solid var(--line)", borderRadius: "10px", background: "var(--bg)", fontSize: "13.5px", outline: "none" }}
            autoFocus
          />
          <button className="primary-button" type="submit" disabled={loading || !input.trim()} style={{ padding: "11px 18px" }}>
            Send
          </button>
        </form>

      </div>
    </div>
  );
}