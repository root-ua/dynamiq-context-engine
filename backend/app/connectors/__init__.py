"""External-source connectors.

A connector pulls content from a third-party system (Google Drive,
Confluence, Notion, ...) into the workspace as ``episode`` rows tagged
with their source-system ACL. The bi-temporal graph extraction pipeline
then derives entities and edges from those episodes; the per-source
ACL filter at query time restricts what each user sees back.

To add a connector:

1. Subclass :class:`app.connectors.base.CrawlerConnector`.
2. Register it in :mod:`app.connectors.registry` under a stable
   ``connector_kind`` string.
3. Wire the OAuth callback route in ``app.api.rest.connectors``.

The framework owns the ``episode`` upsert, the ``episode_acl`` projection,
and audit-logging. Connectors only need to yield :class:`CrawledItem`
instances and produce ACL entries.
"""
