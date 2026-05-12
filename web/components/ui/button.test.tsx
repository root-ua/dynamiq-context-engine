import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Button } from "./button";

describe("Button", () => {
  it("renders the label", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("applies the destructive variant classes", () => {
    render(<Button variant="destructive">Delete</Button>);
    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn.className).toMatch(/bg-destructive/);
  });

  it("sizes icon-only buttons to a square", () => {
    render(
      <Button size="icon" aria-label="menu">
        <svg data-testid="icon" />
      </Button>,
    );
    const btn = screen.getByRole("button", { name: "menu" });
    expect(btn.className).toMatch(/h-9/);
    expect(btn.className).toMatch(/w-9/);
  });

  it("passes asChild through so wrapping elements keep our classes", () => {
    render(
      <Button asChild>
        <a href="/x">go</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "go" });
    expect(link.className).toMatch(/bg-primary/);
  });
});
