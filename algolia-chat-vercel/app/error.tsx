"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div style={{ padding: "2rem", maxWidth: "600px", margin: "0 auto", fontFamily: "system-ui" }}>
      <h2 style={{ color: "#f87171" }}>Что-то пошло не так</h2>
      <pre style={{ background: "#18181b", padding: "1rem", borderRadius: "8px", overflow: "auto", fontSize: "0.875rem" }}>
        {error.message}
      </pre>
      <p style={{ color: "#71717a", fontSize: "0.875rem" }}>
        Убедитесь, что в Vercel задан <strong>Root Directory: algolia-chat-vercel</strong>.
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
        Попробовать снова
      </button>
    </div>
  );
}
