import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./dialog";

describe("Dialog", () => {
  it("renders a close button with an accessible label", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Hello</DialogTitle>
            <DialogDescription>Some description.</DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>,
    );

    // Radix exposes the close button with an sr-only "Close" label.
    expect(screen.getByText("Close")).toBeInTheDocument();
    // Title and description must render so screen readers can reach them.
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Some description.")).toBeInTheDocument();
  });
});
