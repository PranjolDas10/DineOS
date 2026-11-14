import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";

const sans = Geist({ subsets: ["latin"], variable: "--font-geist" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

export const metadata: Metadata = {
  title: { default: "DineOS", template: "%s | DineOS" },
  description: "Food cost, profit by channel and labor for an independent restaurant.",
};

// Runs before first paint, so a saved light/dark choice never flashes the other theme.
const applyTheme = `try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // The script above sets data-theme before React hydrates, so the attribute differs on purpose.
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: applyTheme }} />
      </head>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
