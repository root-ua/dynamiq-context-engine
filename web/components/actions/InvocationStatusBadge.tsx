import { Badge } from "@/components/ui/badge";
import type { ActionStatus } from "@/lib/api/types";

const VARIANTS: Record<
  ActionStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  pending: "outline",
  approved: "secondary",
  executing: "secondary",
  completed: "default",
  failed: "destructive",
  rejected: "destructive",
};

export function InvocationStatusBadge({ status }: { status: ActionStatus }) {
  return <Badge variant={VARIANTS[status]}>{status}</Badge>;
}
