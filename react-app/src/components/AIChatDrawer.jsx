import { useState, useRef, useEffect } from "react";
import { API_BASE, getToken } from "../api.js";
import { Icon } from "./Kpi.jsx";

export default function AIChatDrawer({ onClose, period }) {
  const [messages, setMessages] = useState([
    {
      sender: "ai",
      text: `Hello! I'm your ArthPulse AI Assistant. I am grounded in your ${period} financial records. Ask me about sales, sales drivers, inventory, or cash flow!`,
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatBottomRef = useRef(null);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendMessage = async (e) => {
    e.preventDefault();

    const question = input.trim();
    if (!question || loading) return;

    setInput("");
    setMessages((previous) => [
      ...previous,
      { sender: "user", text: question },
    ]);
    setLoading(true);

    try {
      const token = getToken();

      const response = await fetch(`${API_BASE}/api/ai/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          question,
          period,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (response.status === 401) {
        throw new Error(
          "Your session has expired. Please sign in again."
        );
      }

      if (response.status === 403) {
        throw new Error(
          "You do not have permission to use this feature."
        );
      }

      if (!response.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((item) => item.msg).join("; ")
          : data.detail;

        throw new Error(
          detail || `The assistant request failed (${response.status}).`
        );
      }

      if (
        typeof data.answer !== "string" ||
        !data.answer.trim()
      ) {
        throw new Error("The assistant returned an empty response.");
      }

      setMessages((previous) => [
        ...previous,
        {
          sender: "ai",
          text: data.answer,
          engine: data.engine,
          status: data.status,
        },
      ]);
    } catch (err) {
      setMessages((previous) => [
        ...previous,
        {
          sender: "ai",
          text: `Unable to get a response: ${err.message}`,
          error: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal ai-chat-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Arth AI Assistant"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: "520px",
          height: "600px",
          display: "flex",
          flexDirection: "column",
          padding: 0,
        }}
      >
        {/* Chat Header */}
        <div
          style={{
            padding: "18px 22px",
            borderBottom: "1px solid var(--line)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "var(--soft)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span
              style={{
                display: "grid",
                placeItems: "center",
                width: "32px",
                height: "32px",
                borderRadius: "50%",
                background: "var(--green)",
                color: "#fff",
              }}
            >
              <Icon name="spark" size={16} />
            </span>

            <div>
              <h3 style={{ fontSize: "16px", margin: 0 }}>
                Arth AI Assistant
              </h3>
              <small
                style={{ color: "var(--muted)", fontSize: "11px" }}
              >
                Grounded in business data ({period})
              </small>
            </div>
          </div>

          <button
            className="secondary-button"
            onClick={onClose}
            style={{ padding: "6px 10px", fontSize: "12px" }}
          >
            ✕ Close
          </button>
        </div>

        {/* Chat Messages */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "20px",
            display: "flex",
            flexDirection: "column",
            gap: "14px",
          }}
        >
          {messages.map((message, index) => (
            <div
              key={index}
              style={{
                alignSelf:
                  message.sender === "user" ? "flex-end" : "flex-start",
                maxWidth: "85%",
                padding: "12px 16px",
                borderRadius:
                  message.sender === "user"
                    ? "16px 16px 2px 16px"
                    : "16px 16px 16px 2px",
                background:
                  message.sender === "user"
                    ? "var(--green)"
                    : "var(--soft)",
                color:
                  message.sender === "user" ? "#fff" : "var(--ink)",
                fontSize: "13.5px",
                lineHeight: "1.5",
                whiteSpace: "pre-wrap",
                overflowWrap: "anywhere",
                boxShadow: "var(--shadow)",
              }}
            >
              {message.text}
            </div>
          ))}

          {loading && (
            <div
              role="status"
              style={{
                alignSelf: "flex-start",
                padding: "12px 16px",
                borderRadius: "16px",
                background: "var(--soft)",
                color: "var(--muted)",
                fontSize: "13px",
              }}
            >
              Analyzing business data…
            </div>
          )}

          <div ref={chatBottomRef} />
        </div>

        {/* Chat Input */}
        <form
          onSubmit={sendMessage}
          style={{
            padding: "16px 20px",
            borderTop: "1px solid var(--line)",
            display: "flex",
            gap: "10px",
            background: "var(--card)",
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask e.g. 'Why did sales change this month?'"
            aria-label="Ask Arth AI Assistant"
            style={{
              flex: 1,
              minWidth: 0,
              padding: "11px 14px",
              border: "1px solid var(--line)",
              borderRadius: "10px",
              background: "var(--bg)",
              fontSize: "13.5px",
              outline: "none",
            }}
            autoFocus
          />

          <button
            className="primary-button"
            type="submit"
            disabled={loading || !input.trim()}
            style={{ padding: "11px 18px" }}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}