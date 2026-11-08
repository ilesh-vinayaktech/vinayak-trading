import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Shell } from "@/components/layout/Shell";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vinayak Trading Research Console",
  description: "Read-only view of data, benchmark and research state",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
