import type { Metadata } from "next";
import "./globals.css";
import "./workspace.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "BLUM | Financial research workspace",
  description: "Inspect research decisions, paper execution, costs and benchmark evidence across equities, ETFs and Forex."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

