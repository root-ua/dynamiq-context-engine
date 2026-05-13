"use client";

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import type { IChangeEvent } from "@rjsf/core";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label as FormLabel } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { actionsApi } from "@/lib/api/endpoints";
import type { ActionType } from "@/lib/api/types";

interface Props {
  workspaceId: string;
  actionType: ActionType;
  /** Optional default input values, e.g. when invoked from an edge timeline. */
  defaults?: Record<string, unknown>;
  onInvoked?: (invocationId: string) => void;
}

export function ActionInvocationForm({
  workspaceId,
  actionType,
  defaults,
  onInvoked,
}: Props) {
  const qc = useQueryClient();
  const { push } = useToast();
  const [formData, setFormData] = React.useState<Record<string, unknown>>(
    defaults ?? {},
  );
  const [idempotencyKey, setIdempotencyKey] = React.useState(() =>
    crypto.randomUUID(),
  );

  const invoke = useMutation({
    mutationFn: () =>
      actionsApi.invoke(workspaceId, actionType.slug, {
        input: formData,
        idempotency_key: idempotencyKey,
      }),
    onSuccess: (inv) => {
      push({
        title: `Action ${inv.status}`,
        description: `${actionType.name} — ${inv.id.slice(0, 8)}`,
      });
      onInvoked?.(inv.id);
      // Refresh invocation lists.
      void qc.invalidateQueries({
        queryKey: ["action-invocations", workspaceId],
      });
      // Re-roll the key so re-submitting from the same form treats it as a
      // new invocation rather than the cached one.
      setIdempotencyKey(crypto.randomUUID());
    },
    onError: (err) =>
      push({
        title: "Invocation failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      }),
  });

  return (
    <Card>
      <CardHeader className="space-y-1">
        <CardTitle className="text-base">{actionType.name}</CardTitle>
        {actionType.description && (
          <p className="text-sm text-muted-foreground">
            {actionType.description}
          </p>
        )}
        <div className="flex flex-wrap gap-1.5 pt-1">
          <Badge variant="secondary">role: {actionType.required_role}</Badge>
          {actionType.requires_approval && (
            <Badge variant="outline">requires approval</Badge>
          )}
          {actionType.side_effects.map((s) => (
            <Badge key={s} variant="outline">
              {s}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rjsf-compact">
          <Form
            schema={actionType.input_schema}
            formData={formData}
            validator={validator}
            onChange={(e: IChangeEvent) =>
              setFormData(
                (e.formData as Record<string, unknown> | undefined) ?? {},
              )
            }
            uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="idempotency-key" className="text-xs">
            Idempotency key
          </FormLabel>
          <div className="flex items-center gap-2">
            <Input
              id="idempotency-key"
              value={idempotencyKey}
              onChange={(e) => setIdempotencyKey(e.target.value)}
              className="font-mono text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => setIdempotencyKey(crypto.randomUUID())}
              type="button"
            >
              Regenerate
            </Button>
          </div>
        </div>
        <div className="flex justify-end">
          <Button disabled={invoke.isPending} onClick={() => invoke.mutate()}>
            {invoke.isPending ? "Running…" : "Invoke"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
