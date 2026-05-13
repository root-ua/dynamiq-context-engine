import { describe, expect, it } from "vitest";

import { getNavGroups, isActive } from "./nav-config";

describe("getNavGroups", () => {
  it("prefixes every item with the workspace slug", () => {
    const groups = getNavGroups("acme");
    for (const group of groups) {
      for (const item of group.items) {
        expect(item.href.startsWith("/acme")).toBe(true);
      }
    }
  });

  it("exposes every expected top-level destination", () => {
    const groups = getNavGroups("acme");
    const hrefs = groups.flatMap((g) => g.items.map((i) => i.href)).sort();
    expect(hrefs).toContain("/acme");
    expect(hrefs).toContain("/acme/documents");
    expect(hrefs).toContain("/acme/entities");
    expect(hrefs).toContain("/acme/graph");
    expect(hrefs).toContain("/acme/ontology");
    expect(hrefs).toContain("/acme/agent");
    expect(hrefs).toContain("/acme/playground");
    expect(hrefs).toContain("/acme/activity");
    expect(hrefs).toContain("/acme/search");
    expect(hrefs).toContain("/acme/episodes");
    expect(hrefs).toContain("/acme/settings");
  });
});

describe("isActive", () => {
  const base = "/acme";
  const doc = { href: "/acme/documents", label: "Documents", icon: () => null };
  const home = { href: "/acme", label: "Home", icon: () => null };

  it("treats the workspace root as active only on an exact match", () => {
    expect(isActive("/acme", home, base)).toBe(true);
    expect(isActive("/acme/documents", home, base)).toBe(false);
  });

  it("treats nested routes as active for non-root nav items", () => {
    expect(isActive("/acme/documents", doc, base)).toBe(true);
    expect(isActive("/acme/documents/abc-123", doc, base)).toBe(true);
    expect(isActive("/acme/entities", doc, base)).toBe(false);
  });

  it("is falsy for null/undefined pathnames", () => {
    expect(isActive(null, doc, base)).toBe(false);
    expect(isActive(undefined, doc, base)).toBe(false);
  });
});
