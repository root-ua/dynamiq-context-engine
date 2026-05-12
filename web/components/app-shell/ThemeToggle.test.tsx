import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const setTheme = vi.fn();

vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: "system",
    setTheme,
  }),
}));

import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("cycles system → light → dark on click", async () => {
    setTheme.mockClear();
    render(<ThemeToggle />);
    const btn = screen.getByRole("button", { name: /toggle theme/i });
    await userEvent.click(btn);
    expect(setTheme).toHaveBeenCalledWith("light");
  });
});
