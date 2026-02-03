"use client";

import { useState, useCallback } from "react";

function getAlgoliaConfig() {
  const appId = (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_ALGOLIA_APPLICATION_ID) || "SRC8UTYBUO";
  const apiKey = (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_ALGOLIA_API_KEY) || "a5eed7751bad8e4535ace1f3b08f52c5";
  const agentId = (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_ALGOLIA_AGENT_ID) || "1feae05a-7e87-4508-88c8-2d7da88e30de";
  const base = String(appId).toLowerCase();
  return {
    appId: String(appId),
    apiKey: String(apiKey),
    agentId: String(agentId),
    apiUrl: `https://${base}.algolia.net/agent-studio/1/agents/${agentId}/completions?stream=true&compatibilityMode=ai-sdk-5`,
  };
}

type Message = { role: "user" | "assistant"; content: string };

function useAlgoliaChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [status, setStatus] = useState<"ready" | "streaming" | "error">("ready");
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim()) return;
    const cfg = getAlgoliaConfig();
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text.trim() }]);
    setStreamingContent("");
    setStatus("streaming");

    try {
      const res = await fetch(cfg.apiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-algolia-application-id": cfg.appId,
          "x-algolia-api-key": cfg.apiKey,
        },
        body: JSON.stringify({
          messages: [{ role: "user", parts: [{ text: text.trim() }] }],
        }),
      });

      if (!res.ok) {
        const body = await res.text();
        let errMsg = body;
        try {
          const j = JSON.parse(body);
          errMsg = j.message ?? j.detail ?? body;
        } catch {
          if (body.startsWith("<!")) errMsg = "Algolia вернул HTML (возможно Cloudflare).";
        }
        throw new Error(errMsg);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      let buf = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const obj = JSON.parse(line.slice(6).trim());
                if (obj.type === "text-delta" && typeof obj.delta === "string") {
                  acc += obj.delta;
                  setStreamingContent(acc);
                }
                if (obj.error) {
                  setError(String(obj.error));
                  setStatus("error");
                  return;
                }
              } catch {
                // skip non-JSON lines
              }
            }
          }
        }
      }

      setMessages((prev) => [...prev, { role: "assistant", content: acc }]);
      setStreamingContent("");
      setStatus("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
      setStreamingContent("");
    }
  }, []);

  return { messages, streamingContent, status, error, sendMessage };
}

export default function ChatPage() {
  const { messages, streamingContent, status, error, sendMessage } = useAlgoliaChat();

  return (
    <div className="chat-layout">
      <header className="chat-header">
        <h1>Kinescope — база знаний</h1>
        <p className="chat-subtitle">Чат с ассистентом (Algolia Agent)</p>
      </header>

      <main className="chat-main">
        <div className="chat-messages">
          {messages.length === 0 && !streamingContent && (
            <div className="chat-welcome">
              <p>Задайте вопрос по документации Kinescope.</p>
              <p className="chat-hint">Например: «Как загрузить видео?»</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`chat-message chat-message--${msg.role}`}>
              <span className="chat-message-role">{msg.role === "user" ? "Вы" : "Ассистент"}</span>
              <div className="chat-message-content">{msg.content}</div>
            </div>
          ))}
          {streamingContent && (
            <div className="chat-message chat-message--assistant">
              <span className="chat-message-role">Ассистент</span>
              <div className="chat-message-content">{streamingContent}</div>
            </div>
          )}
          {error && (
            <div className="chat-message chat-message--assistant chat-message--error">
              <span className="chat-message-role">Ошибка</span>
              <div className="chat-message-content">{error}</div>
            </div>
          )}
        </div>

        <form
          className="chat-form"
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const textarea = form.querySelector("textarea");
            const text = textarea?.value?.trim();
            if (text) {
              sendMessage(text);
              textarea!.value = "";
            }
          }}
        >
          <textarea
            placeholder="Спросите что угодно..."
            rows={1}
            disabled={status === "streaming"}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button type="submit" disabled={status === "streaming"}>
            Отправить
          </button>
        </form>
      </main>
    </div>
  );
}
