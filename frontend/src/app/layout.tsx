import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TraceAgent — AI Agent Flight Recorder & Time-Travel Debugger",
  description: "Local-first deterministic replay, SHA-256 audit chain, and step-level flamegraph.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0B0F17] text-[#F9FAFB] antialiased selection:bg-[#38BDF8]/30">
        {children}
      </body>
    </html>
  );
}
