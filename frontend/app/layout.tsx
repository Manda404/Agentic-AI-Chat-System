import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Agentic RAG Platform",
  description: "Agentic RAG chat UI with multi-agent workflow visibility",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}

