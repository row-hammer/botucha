"use client";

import {
  Activity,
  Brain,
  Gauge,
  MessageSquareHeart,
  Network,
  Settings2,
  SlidersHorizontal,
  SpellCheck,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { type Lang, useLang, useT } from "@/lib/i18n";
import { useLive } from "@/lib/live";

export const NAV = [
  { href: "/", key: "overview", icon: Gauge },
  { href: "/pipeline/", key: "pipeline", icon: Workflow },
  { href: "/quality/", key: "quality", icon: SpellCheck },
  { href: "/thinking/", key: "thinking", icon: Activity },
  { href: "/memory/", key: "memory", icon: Brain },
  { href: "/people/", key: "people", icon: Network },
  { href: "/ratings/", key: "ratings", icon: MessageSquareHeart },
  { href: "/controls/", key: "controls", icon: SlidersHorizontal },
  { href: "/settings/", key: "settings", icon: Settings2 },
] as const;

export function AppSidebar() {
  const t = useT();
  const path = usePathname();
  const status = useLive((s) => s.status);
  const { lang, setLang } = useLang();
  const { theme, setTheme } = useTheme();
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <div className="grid size-8 place-items-center rounded-md bg-sidebar-primary font-semibold text-sidebar-primary-foreground">
            B
          </div>
          <div className="min-w-0 group-data-[collapsible=icon]:hidden">
            <div className="font-semibold leading-tight">{t("app.title")}</div>
            <div className="truncate text-muted-foreground text-xs">{t("app.subtitle")}</div>
          </div>
        </div>
        <div className="px-2 group-data-[collapsible=icon]:hidden">
          <StatusBadge state={status?.bot} />
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map(({ href, key, icon: Icon }) => (
                <SidebarMenuItem key={href}>
                  <SidebarMenuButton
                    asChild
                    isActive={href === "/" ? path === "/" : path.startsWith(href)}
                    tooltip={t(`nav.${key}`)}
                  >
                    <Link href={href}>
                      <Icon />
                      <span>{t(`nav.${key}`)}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="gap-2 group-data-[collapsible=icon]:hidden">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">{t("common.language")}</span>
          <div className="flex gap-1">
            {(["en", "lt"] as Lang[]).map((l) => (
              <Button key={l} size="xs" variant={lang === l ? "default" : "outline"} onClick={() => setLang(l)}>
                {l.toUpperCase()}
              </Button>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">{t("common.theme")}</span>
          <div className="flex gap-1">
            {(["light", "dark", "system"] as const).map((m) => (
              <Button key={m} size="xs" variant={theme === m ? "default" : "outline"} onClick={() => setTheme(m)}>
                {t(`common.${m}`)}
              </Button>
            ))}
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
