"""External-source integrations (Google Docs, etc.).

V1 only ships Google Docs. The pattern (per-user OAuth, selection picker,
manual sync) is intended to generalize to Slack/Notion/Drive later, but the
abstraction layer waits until we have a second concrete integration to learn
from.
"""
