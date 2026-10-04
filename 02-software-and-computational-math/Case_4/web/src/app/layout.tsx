import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import AuthStatus from "@/components/AuthStatus";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Neighbourhood Flags | Case 4",
  description: "Calgary neighbourhood smoke and hail assessments.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <nav className="border-b border-zinc-200 bg-white px-6 py-3 sm:px-12">
          <div className="mx-auto flex max-w-7xl items-center justify-between">
            <Link
              href="/"
              className="text-sm font-semibold text-zinc-900 hover:text-zinc-700"
            >
              HailsTech Calgary
            </Link>
            <AuthStatus />
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
