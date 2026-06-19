import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Open Market Intelligence",
  description: "Local-first public market intelligence dashboard.",
};

const themeInitScript = `
try {
  var omiTheme = window.localStorage.getItem("omi:settings:color");
  if (omiTheme === "light" || omiTheme === "dark") {
    document.documentElement.dataset.theme = omiTheme;
  }
} catch (error) {}
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
