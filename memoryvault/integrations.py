"""Workplace integrations — surface & capture memory where employees work.

Registry of the tools employees live in (Slack, Teams, Notion, Jira,
Zendesk, Google Drive). Each integration both captures memory (what the
team learns in that tool) and surfaces it (answers/context inside the tool).
Definitions + activation state here; the wire protocol reuses the connector
interface (extract/load) and the webhook inbox, so no new plumbing.
"""
from __future__ import annotations

import os

CATALOG = {
    "slack":     {"name": "Slack", "captures": "messages, decisions in channels",
                  "surfaces": "answers via /memory slash command", "color": "#611f69"},
    "teams":     {"name": "Microsoft Teams", "captures": "chats, meeting notes",
                  "surfaces": "a Teams bot", "color": "#4b53bc"},
    "notion":    {"name": "Notion", "captures": "docs & wikis",
                  "surfaces": "inline memory blocks", "color": "#111"},
    "jira":      {"name": "Jira", "captures": "tickets, resolutions",
                  "surfaces": "context on related issues", "color": "#0052cc"},
    "zendesk":   {"name": "Zendesk", "captures": "support tickets & macros",
                  "surfaces": "suggested memory on new tickets", "color": "#03363d"},
    "gdrive":    {"name": "Google Drive", "captures": "documents",
                  "surfaces": "memory from your files", "color": "#1a73e8"},
    "confluence":{"name": "Confluence", "captures": "wiki pages",
                  "surfaces": "linked memory", "color": "#172b4d"},
}

# env var per integration that activates it (paste a token -> live)
_TOKEN_ENV = {
    "slack": "SLACK_BOT_TOKEN", "teams": "TEAMS_APP_TOKEN",
    "notion": "NOTION_TOKEN", "jira": "JIRA_TOKEN",
    "zendesk": "ZENDESK_TOKEN", "gdrive": "GOOGLE_TOKEN",
    "confluence": "CONFLUENCE_TOKEN",
}


def live(name: str) -> bool:
    return bool(os.environ.get(_TOKEN_ENV.get(name, ""), ""))


def catalog() -> list:
    out = []
    for key, meta in CATALOG.items():
        out.append({"id": key, **meta, "live": live(key),
                    "token_env": _TOKEN_ENV.get(key)})
    return out
