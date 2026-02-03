"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="ru">
      <body style={{ margin: 0, padding: "2rem", fontFamily: "system-ui", background: "#0a0a0a", color: "#e4e4e7" }}>
        <h2 style={{ color: "#f87171" }}>Ошибка приложения</h2>
        <pre style={{ background: "#18181b", padding: "1rem", borderRadius: "8px", overflow: "auto", fontSize: "0.875rem" }}>
          {error.message}
        </pre>
        <p style={{ color: "#71717a", fontSize: "0.875rem" }}>
          В настройках проекта Vercel укажите <strong>Root Directory: algolia-chat-vercel</strong>.
        </p>
        <button
          onClick={reset}
          style={{
            marginTop: "1rem",
            padding: "0.5rem 1rem",
            background: "#6d559e",
            color: "#fff",
            border: "none",
            borderRadius: "8px",
            cursor: "pointer",
          }}
        >
          Обновить
        </button>
      </body>
    </html>
  );
}
