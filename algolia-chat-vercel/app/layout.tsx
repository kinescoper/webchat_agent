import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kinescope — база знаний (Algolia)",
  description: "Чат с ассистентом по документации Kinescope",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
