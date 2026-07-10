import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Multi Agent Starter UI",
  description: "Beginner-friendly multi-agent chat UI",
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


