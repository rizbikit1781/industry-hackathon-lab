import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Nav from "@/components/Nav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "SnowTech",
  description: "Snow and ice dispatch for Calgary 311: riskiest ice first, replanned live.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex h-full min-h-0 flex-col bg-bg font-sans text-ink">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface-2 focus:px-3 focus:py-2">
          Skip to content
        </a>
        <Nav />
        <main id="main" className="flex min-h-0 flex-1 flex-col">
          {children}
        </main>
      </body>
    </html>
  );
}
