import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Open Market Intelligence",
  description: "Local-first public market intelligence dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
