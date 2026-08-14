import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic RAG Platform",
  description: "Agentic RAG chat UI with multi-agent workflow visibility",
};

// Applique le thème sauvegardé (ou la préférence système) AVANT le premier
// rendu pour éviter un flash de mauvais thème (FOUC) au chargement.
const themeInitScript = `
(function () {
  try {
    var stored = window.localStorage.getItem("agentic-rag-platform-theme");
    var theme = stored === "light" || stored === "dark"
      ? stored
      : (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body style={{ margin: 0 }} suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}

