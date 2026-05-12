# Google Drive connector — quickstart

Two ways to run the connector:

* **Mock mode** (default in `docker-compose.override.yml`) — three canned
  documents with deterministic ACLs, no Google credentials required.
  Great for local demos and CI.
* **Live mode** — real Google OAuth + real Drive crawl. Requires a Google
  Cloud project + OAuth client.

## Mock mode walk-through

```bash
docker compose down -v   # fresh DB so the schema is up-to-date
docker compose up -d
docker exec memory-platform-backend-1 alembic upgrade head
```

Open `http://localhost:53000`, sign up, create a workspace.

1. **Settings → Integrations → Connectors → "Add Google Drive"**.
   The mock OAuth completes immediately. The crawler starts in the
   worker container and ingests three documents:

   | External id        | Title                            | Default ACL                           |
   |--------------------|----------------------------------|---------------------------------------|
   | `alpha-shared`     | Q3 OKRs                          | domain `acme.com`                     |
   | `bravo-team`       | Backend Roadmap (Eng leads)      | users `alice@acme.com`, `carol@acme.com` |
   | `charlie-private`  | Compensation review              | user `hr@acme.com` only               |

   The mock data lives in `backend/app/connectors/_drive_mock.py`.

2. **Sources** in the sidebar. As workspace owner you see all three
   documents (admin/owner bypasses the per-source ACL).

   Mock mode also inserts a fixed set of canned **facts** (edges)
   rooted at each episode — so the demo works end-to-end without an
   `ANTHROPIC_API_KEY` for LLM extraction. The fact set is:

   | Source                | Facts                                                                |
   |-----------------------|----------------------------------------------------------------------|
   | `alpha-shared`        | Engineering ↦ Acme, Alice/Bob/Carol ↦ Engineering, Engineering tagged Q3 OKRs |
   | `bravo-team`          | Alice ↦ Connector framework, Carol ↦ ACL filter design, Bob ↦ On-call rotation |
   | `charlie-private`     | David ↦ Staff Engineer promotion                                     |

   Open any source in **Sources → click a row** to see the derived
   edges. Real-mode (no `MOCK_DRIVE`) uses the LLM extraction pipeline
   instead and requires `ANTHROPIC_API_KEY` + `OPENAI_API_KEY`.

3. **Settings → Identity → "Connect Google"**. The mock flow links your
   `app_user.email` as the Google identity bridge. To exercise the
   visibility filter, edit your user row to use one of the ACL emails:

   ```sql
   UPDATE app_user SET email = 'alice@acme.com' WHERE id = '<your-id>';
   ```

   Then re-connect from the Identity page. Now Sources will be filtered
   by the per-document ACLs.

4. **Personal access token**. Settings → Integrations → "Create token".
   The token is shown once — copy it. Wire Claude Code:

   ```jsonc
   // ~/.claude.json
   {
     "mcpServers": {
       "dynamiq": {
         "type": "http",
         "url": "http://localhost:58000/api/mcp/rpc",
         "headers": { "Authorization": "Bearer mem_user_..." }
       }
     }
   }
   ```

   In Claude Code, ask: *"What are the Q3 OKRs?"* — search_memory only
   returns facts from documents your identity grants access to.

5. **Verify the matrix**: invite a second user to the workspace as an
   editor with email `bob@acme.com`. Repeat the Connect Google step for
   them. They'll only see `alpha-shared` (the domain-shared doc) — not
   the per-user-shared `bravo-team` or `charlie-private`.

## Smoke test the MCP loop end-to-end

A self-contained curl-equivalent test that exercises the full
production stack — real HTTP, real worker, real `Bearer mem_user_*`
on `/api/mcp/rpc`. Useful for one-off verification after deployment.

The full script lives at `/tmp/mcp_smoke.py` (created during Phase 10);
the essentials of what it does:

```bash
TOKEN="mem_user_..."   # mint via the UI: Settings → Integrations → Create token (kind=user)
BASE="http://localhost:58000"

# tools/list — should advertise 12 tools
curl -sX POST "$BASE/api/mcp/rpc" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools | length'

# search_memory — only ACL-permitted facts come back
curl -sX POST "$BASE/api/mcp/rpc" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"search_memory",
                 "arguments":{"query":"engineering","limit":10,
                              "include_kinds":["edge"]}}}' | jq
```

Expected: same query returns different result sets for two `mem_user_*`
tokens minted by two different users in the same workspace, where only
one has connected a matching Google identity.

## Live mode (real Google account)

1. Create a Google Cloud project and an OAuth 2.0 client (Web type) at
   <https://console.cloud.google.com/apis/credentials>.

2. Add these redirect URIs:

   ```
   http://localhost:53000/connectors/oauth-callback
   http://localhost:53000/identity/google/callback
   ```

   (And the same with your production hostname when deploying.)

3. Enable the Google Drive API on the project.

4. Set env vars on the backend + worker (e.g. in a local `.env`):

   ```
   MOCK_DRIVE=
   GOOGLE_OAUTH_CLIENT_ID=...
   GOOGLE_OAUTH_CLIENT_SECRET=...
   CONNECTOR_SECRET_KEY=<long-random>
   WEB_BASE_URL=http://localhost:53000
   ```

5. `docker compose up -d` and follow the same UI flow. The OAuth
   consent screen will be Google's real one; the crawler reads your
   actual files via `files.list` + `permissions.list`.

   Optional: to populate group memberships on `user_external_identity`,
   the Drive scope is not enough — you'd also need
   `admin.directory.group.readonly` and a Workspace admin to grant it.
   Without that, group ACL entries on Drive files only resolve for
   users whose identity row contains the matching group manually
   (`groups_resolution='self'`).

## Troubleshooting

* **"Lost workspace context" on the OAuth callback page** — the
  callback page reads workspace from `sessionStorage`. If the consent
  flow opened a new tab and the original tab was closed, that storage is
  gone. Start the install again.

* **`processing_status='failed'` on episodes** — extraction failures
  (LLM errors, ontology validation) leave the episode in `failed` with
  `processing_error` populated. Restart extraction by editing/rewriting
  content in the source and triggering a re-crawl from the connector
  detail page.

* **Connector stuck in `authorizing`** — disconnect from the connector
  detail page and add it again. The OAuth state was lost (e.g. consent
  window closed before completion).

* **Owner sees fewer documents than expected** — the ACL bypass is
  driven by the workspace_member role. Confirm your user has role
  `owner` or `admin`:

  ```sql
  SELECT role FROM workspace_member
   WHERE user_id = '<your-id>' AND workspace_id = '<ws-id>';
  ```

* **Member sees zero connector-derived documents** — they haven't
  connected an identity yet, OR their email doesn't match any per-user
  ACL entry. The ConnectIdentityBanner nudges them; the Sources page
  surfaces the gap explicitly.
