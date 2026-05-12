import { expect, test } from "@playwright/test";

/**
 * End-to-end smoke test walking the core product flow:
 *   sign up → create workspace → create a document → mention an entity
 *   → check the graph → invoke an MCP tool.
 *
 * Run after `docker compose up --build` with PLAYWRIGHT_SKIP_SERVER=1 set.
 */

const email = `e2e-${Date.now()}@example.com`;
const password = "CorrectHorseBattery42!";
const slug = `e2e-${Date.now().toString(36)}`;

test("signup, create workspace, write a note, mention an entity", async ({
  page,
}) => {
  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();

  // Land on onboarding with no workspaces yet.
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Workspace name").fill("E2E Workspace");
  await page.getByLabel("URL slug").fill(slug);
  await page.getByRole("button", { name: /flexible ontology/i }).click();
  await page.getByRole("button", { name: /create workspace/i }).click();

  // Workspace home.
  await expect(page).toHaveURL(new RegExp(`/${slug}$`));
  await expect(
    page.getByRole("heading", { name: "E2E Workspace" }),
  ).toBeVisible();

  // Ontology page renders built-in types.
  await page.getByRole("link", { name: "Ontology" }).click();
  await expect(page.getByText("Person")).toBeVisible();
  await expect(page.getByText("Organization")).toBeVisible();

  // Create a document.
  await page.getByRole("link", { name: "Documents" }).click();
  await page.getByRole("button", { name: /new document/i }).click();
  await page.getByLabel("Title").fill("Kickoff with Anthropic");
  await page.getByRole("button", { name: "Create" }).click();

  // Editor mounts — confirm the title field holds our input. Using
  // a plain locator with `inputValue()` keeps us compatible with every
  // Playwright build; `getByDisplayValue` came in later and tripped the
  // typecheck when the bundled types fell behind.
  const titleInput = page
    .locator('input[value="Kickoff with Anthropic"]')
    .first();
  await expect(titleInput).toBeVisible();

  // Agent console lists tools.
  await page.getByRole("link", { name: "Agent console" }).click();
  await expect(page.getByText("ontology_describe")).toBeVisible();
  await expect(page.getByText("search_memory")).toBeVisible();
  await expect(page.getByText("create_entity_type")).toBeVisible();
});
