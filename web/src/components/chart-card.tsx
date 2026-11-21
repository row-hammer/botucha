import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ChartCard({
  title,
  children,
  empty,
  emptyText,
}: {
  title: string;
  children: React.ReactNode;
  empty?: boolean;
  emptyText?: string;
}) {
  return (
    <Card className="gap-2">
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="h-64">
        {empty ? (
          <div className="grid h-full place-items-center text-muted-foreground text-sm">{emptyText}</div>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
