import type { Metadata } from "next";
import localFont from "next/font/local";

import { AppShell } from "@/components/app-shell";
import "./globals.css";

const geistMono = localFont({
  src: "../node_modules/next/dist/next-devtools/server/font/geist-mono-latin.woff2",
  variable: "--font-wordmark",
  display: "swap",
  preload: true,
});

export const metadata: Metadata = {
  title: "MemoryOS — agent memory layer",
  description: "An explainable long-term memory layer for AI agents.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={geistMono.variable} suppressHydrationWarning>
      <head>
        <script
          id="memoryos-theme-init"
          dangerouslySetInnerHTML={{
            __html: `(() => { try { const stored = localStorage.getItem("memoryos-appearance"); const system = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; const theme = stored === "dark" || stored === "light" ? stored : system; document.documentElement.dataset.theme = theme; document.documentElement.style.colorScheme = theme; } catch {} })();`,
          }}
        />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
