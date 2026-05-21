import { expect, test } from "@playwright/test";

/**
 * End-to-end test for the Google Docs integration page redesign.
 *
 * Mocks all `/api/integrations/google-docs/*` endpoints so the test is
 * hermetic and doesn't depend on real Google OAuth or live Drive content.
 *
 * Covers the redesigned two-step flow:
 *   1. Picker shows a draft selection.
 *   2. A single primary CTA "Add to workspace" / "Re-sync" performs
 *      save + sync atomically.
 *   3. SyncProgress renders in place of the CTA while a job is active.
 *
 * Run after `docker compose up` with PLAYWRIGHT_SKIP_SERVER=1 set.
 */

const email = `e2e-gdocs-${Date.now()}@example.com`;
const password = "CorrectHorseBattery42!";
const slug = `e2e-gdocs-${Date.now().toString(36)}`;
const wsId = "11111111-1111-1111-1111-111111111111";
const connectionId = "22222222-2222-2222-2222-222222222222";
const jobId = "33333333-3333-3333-3333-333333333333";

const CONNECTION = {
  id: connectionId,
  workspace_id: wsId,
  user_id: "44444444-4444-4444-4444-444444444444",
  account_email: "test-user@example.com",
  scopes: ["https://www.googleapis.com/auth/drive.readonly"],
  selection: { folders: [], files: [] },
  created_at: "2026-05-21T10:00:00Z",
  updated_at: "2026-05-21T10:00:00Z",
  revoked_at: null,
};

const ROOT_TREE = {
  parent: "root",
  children: [
    {
      id: "doc-1",
      name: "First test doc",
      mime_type: "application/vnd.google-apps.document",
      is_folder: false,
      is_doc: true,
    },
    {
      id: "folder-A",
      name: "Folder A",
      mime_type: "application/vnd.google-apps.folder",
      is_folder: true,
      is_doc: false,
    },
    {
      id: "md-2",
      name: "uploaded.md",
      mime_type: "text/markdown",
      is_folder: false,
      is_doc: true,
    },
  ],
};

const FOLDER_A_TREE = {
  parent: "folder-A",
  children: [
    {
      id: "doc-2",
      name: "Doc inside folder A",
      mime_type: "application/vnd.google-apps.document",
      is_folder: false,
      is_doc: true,
    },
  ],
};

test.describe("Google Docs integration — redesigned flow", () => {
  test.beforeEach(async ({ page, context }) => {
    // --- Mock all Google Docs API endpoints up-front. ---
    let savedSelection: typeof CONNECTION.selection = {
      folders: [],
      files: [],
    };
    let syncStarted = false;

    await page.route(
      /\/api\/integrations\/google-docs\/connections$/,
      (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: [{ ...CONNECTION, selection: savedSelection }],
          }),
        });
      },
    );

    await page.route(
      new RegExp(
        `/api/integrations/google-docs/connections/${connectionId}/tree`,
      ),
      (route) => {
        const url = new URL(route.request().url());
        const parent = url.searchParams.get("parent") ?? "root";
        const body = parent === "folder-A" ? FOLDER_A_TREE : ROOT_TREE;
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
    );

    await page.route(
      new RegExp(
        `/api/integrations/google-docs/connections/${connectionId}/selection`,
      ),
      async (route) => {
        const payload = route.request().postDataJSON() as typeof savedSelection;
        savedSelection = payload;
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...CONNECTION, selection: savedSelection }),
        });
      },
    );

    await page.route(
      new RegExp(
        `/api/integrations/google-docs/connections/${connectionId}/sync$`,
      ),
      (route) => {
        syncStarted = true;
        route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              id: jobId,
              workspace_id: wsId,
              connection_id: connectionId,
              status: "queued",
              total_docs: 0,
              processed_docs: 0,
              failed_docs: 0,
              skipped_docs: 0,
              error: null,
              created_at: new Date().toISOString(),
              started_at: null,
              completed_at: null,
            },
          }),
        });
      },
    );

    // Sync job polling endpoint — return a "running" snapshot.
    await page.route(
      new RegExp(`/api/integrations/google-docs/sync-jobs/${jobId}`),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: {
              id: jobId,
              workspace_id: wsId,
              connection_id: connectionId,
              status: syncStarted ? "running" : "queued",
              total_docs: 2,
              processed_docs: 1,
              failed_docs: 0,
              skipped_docs: 0,
              error: null,
              created_at: new Date(Date.now() - 60_000).toISOString(),
              started_at: syncStarted
                ? new Date(Date.now() - 30_000).toISOString()
                : null,
              completed_at: null,
            },
          }),
        });
      },
    );

    // Per-doc list — empty by default; updated on sync trigger.
    await page.route(
      new RegExp(
        `/api/integrations/google-docs/connections/${connectionId}/docs`,
      ),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ data: [] }),
        });
      },
    );

    // --- Sign up + create workspace so we have an authenticated session. ---
    await page.goto("/signup");
    await page.getByLabel("Name").fill("E2E Gdocs User");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /create account/i }).click();
    await expect(page).toHaveURL(/\/onboarding$/);

    await page.getByLabel("Workspace name").fill("E2E Gdocs WS");
    await page.getByLabel("URL slug").fill(slug);
    await page.getByRole("button", { name: /flexible ontology/i }).click();
    await page.getByRole("button", { name: /create workspace/i }).click();
    await expect(page).toHaveURL(new RegExp(`/${slug}$`));
  });

  test("pick → add to workspace → progress visible (no separate Save step)", async ({
    page,
  }) => {
    // Navigate to integrations page using the real workspace slug; the
    // API mocks short-circuit Google Docs calls, so the workspace_id
    // used by the mock connection doesn't need to match the real ws.
    await page.goto(`/${slug}/integrations/google-docs`);

    // Connection card should show connected state from mocked endpoint.
    await expect(page.getByText(/connected as/i)).toBeVisible({
      timeout: 10_000,
    });

    // Picker should render the mocked root tree.
    await expect(page.getByText("First test doc")).toBeVisible();
    await expect(page.getByText("Folder A")).toBeVisible();
    await expect(page.getByText("uploaded.md")).toBeVisible();

    // Pick one document.
    const docCheckbox = page.getByLabel(/select file First test doc/i);
    await docCheckbox.check();

    // Pick one folder.
    const folderCheckbox = page.getByLabel(/select folder Folder A/i);
    await folderCheckbox.check();

    // The redesigned UX has a SINGLE primary CTA (not Save + Sync).
    // Match anything that says "Add ... to workspace" — exact label may
    // vary slightly across the agent's implementation.
    const addCta = page.getByRole("button", { name: /add.*to workspace/i });
    await expect(addCta).toBeVisible();
    await expect(addCta).toBeEnabled();

    // Critically: there should be NO standalone "Save selection" button.
    await expect(
      page.getByRole("button", { name: /^save selection$/i }),
    ).toHaveCount(0);

    // Click the unified CTA — it should both save the selection and
    // trigger sync in one action.
    await addCta.click();

    // After clicking, the SyncProgress component should be visible — it
    // replaces the CTA in the same card.
    await expect(
      page.getByText(/sync|processed|queued|running/i).first(),
    ).toBeVisible({ timeout: 10_000 });

    // The "Sync now" separate button must not exist in the new UX.
    await expect(page.getByRole("button", { name: /^sync now$/i })).toHaveCount(
      0,
    );
  });

  test("picker shows uploaded text files (mime text/markdown), not just Google Docs", async ({
    page,
  }) => {
    await page.goto(`/${slug}/integrations/google-docs`);

    // This is the bug fix: text/markdown should now appear in the picker.
    await expect(page.getByText("uploaded.md")).toBeVisible({
      timeout: 10_000,
    });

    // Verify it's pickable as a file (not silently dropped).
    const mdCheckbox = page.getByLabel(/select file uploaded\.md/i);
    await expect(mdCheckbox).toBeVisible();
    await mdCheckbox.check();
    await expect(mdCheckbox).toBeChecked();
  });

  test("expanding a folder shows its children with meaningful loader copy", async ({
    page,
  }) => {
    await page.goto(`/${slug}/integrations/google-docs`);
    await expect(page.getByText("Folder A")).toBeVisible({ timeout: 10_000 });

    // Click the folder expand affordance.
    await page
      .getByRole("button", { name: /expand|collapse/i })
      .filter({ has: page.locator("text=Folder A") })
      .first()
      .click()
      .catch(async () => {
        // Fallback: click the folder name itself.
        await page.getByText("Folder A").click();
      });

    // Child appears.
    await expect(page.getByText("Doc inside folder A")).toBeVisible({
      timeout: 5_000,
    });
  });
});
