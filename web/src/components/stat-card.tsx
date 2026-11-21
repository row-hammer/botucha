import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  tone,
  href,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  tone?: string;
  href?: string;
}) {
  const card = (
    <Card className={cn("h-full py-4", href && "transition-colors group-hover:bg-muted/50")}>
      <CardContent className="flex items-center gap-3 px-4">
        <div className={cn("grid size-9 shrink-0 place-items-center rounded-md bg-muted", tone)}>
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="text-muted-foreground text-xs leading-tight">{label}</div>
          <div className="flex flex-wrap items-baseline gap-x-1.5">
            <span className="whitespace-nowrap font-semibold text-xl tabular-nums">{value}</span>
            {sub ? <span className="text-muted-foreground text-xs tabular-nums">{sub}</span> : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
  return href ? (
    <Link href={href} className="group rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {card}
    </Link>
  ) : (
    card
  );
}
