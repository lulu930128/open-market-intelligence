import type { Metadata } from "next";
import Script from "next/script";
import { I18nProvider } from "@/i18n";
import "./globals.css";

export const metadata: Metadata = {
  title: "Open Market Intelligence",
  description: "Local-first public market intelligence dashboard.",
};

const preferenceInitScript = `
try {
  var omiTheme = window.localStorage.getItem("omi:settings:color");
  var omiHighContrast = window.localStorage.getItem("omi:settings:high-contrast");
  if (omiTheme === "high-contrast") {
    document.documentElement.dataset.theme = "dark";
    if (omiHighContrast !== "false") {
      document.documentElement.dataset.contrast = "high";
    }
  } else if (omiTheme === "light" || omiTheme === "dark") {
    document.documentElement.dataset.theme = omiTheme;
  }
  if (omiHighContrast === "true") {
    document.documentElement.dataset.contrast = "high";
  } else if (omiHighContrast === "false") {
    delete document.documentElement.dataset.contrast;
  }

  var omiLocale = window.localStorage.getItem("omi:settings:language");
  var htmlLang = {
    "zh-TW": "zh-Hant",
    "en-US": "en",
    "ja-JP": "ja"
  }[omiLocale];
  if (htmlLang) {
    document.documentElement.lang = htmlLang;
    document.documentElement.dataset.locale = omiLocale;
  }
} catch (error) {}
document.documentElement.dataset.omiPreferenceBootstrap = "ready";
setTimeout(function () {
  if (document.documentElement.dataset.omiPreferenceState === "pending") {
    // Diagnostic only. I18nProvider owns readiness; CSS owns stalled-JS visibility.
    document.documentElement.dataset.omiPreferenceBootstrap = "timeout";
  }
}, 1500);
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-Hant"
      className="h-full antialiased"
      data-omi-preference-state="pending"
      suppressHydrationWarning
    >
      <head>
        <Script
          id="omi-preference-init"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{ __html: preferenceInitScript }}
        />
      </head>
      <body className="min-h-full flex flex-col">
        <I18nProvider>{children}</I18nProvider>
      </body>
    </html>
  );
}
