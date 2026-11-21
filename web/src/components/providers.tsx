"use client";

import { ThemeProvider } from "next-themes";
import { useEffect } from "react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useLang } from "@/lib/i18n";
import { startLive } from "@/lib/live";

export function Providers({ children }: { children: React.ReactNode }) {
  const lang = useLang((s) => s.lang);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  useEffect(() => startLive(), []);
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <TooltipProvider>
        {children}
        <Toaster richColors position="bottom-right" />
      </TooltipProvider>
    </ThemeProvider>
  );
}
