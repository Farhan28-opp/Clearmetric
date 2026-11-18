import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "ClearMetric — Your AI Business Analyst", template: "%s · ClearMetric" },
  description: "Upload business data, ask questions in plain language, and get answers you can verify: every number comes with its calculation.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
