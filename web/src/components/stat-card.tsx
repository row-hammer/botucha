import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone?: string;
}) {
  return (
    <Card className="py-4">
      <CardContent className="flex items-center gap-3 px-4">
        <div className={cn("grid size-9 place-items-center rounded-md bg-muted", tone)}>
          <Icon className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-muted-foreground text-xs">{label}</div>
          <div className="font-semibold text-xl tabular-nums">{value}</div>
        </div>
      </CardContent>
    </Card>
  );
}
