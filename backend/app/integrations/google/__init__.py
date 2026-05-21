"""Google Workspace integration. V1: Google Docs (My Drive).

Modules:
    oauth        — OAuth 2.0 authorization-code dance + token refresh.
    drive_client — httpx wrapper around Drive v3 (files.list, files.get, files.export).
    sync         — Arq worker job: expand selection → fetch → episode → enqueue_extraction.
"""
