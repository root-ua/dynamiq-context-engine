import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function WorkspaceNotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center gap-4 py-24 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">Not found</h1>
      <p className="text-muted-foreground">
        That document, entity, or page isn't in this workspace. It may have been
        deleted, or you may not have access.
      </p>
      <Button asChild>
        <Link href="/home">Back to workspace home</Link>
      </Button>
    </div>
  );
}
