"""Lightweight Notion API reader for calibration data extraction."""

from __future__ import annotations

import json
import os
import requests
from typing import Any, Dict, List, Optional


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def search(token: str, query: str = "", page_size: int = 20) -> List[dict]:
    """Search across all connected pages/databases."""
    resp = requests.post(
        f"{NOTION_API}/search",
        headers=_headers(token),
        json={"query": query, "page_size": page_size},
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def get_page(token: str, page_id: str) -> dict:
    """Get page metadata."""
    resp = requests.get(
        f"{NOTION_API}/pages/{page_id}",
        headers=_headers(token),
    )
    resp.raise_for_status()
    return resp.json()


def get_blocks(token: str, block_id: str, page_size: int = 100) -> List[dict]:
    """Get all child blocks (content) of a page/block."""
    blocks = []
    url = f"{NOTION_API}/blocks/{block_id}/children?page_size={page_size}"
    while url:
        resp = requests.get(url, headers=_headers(token))
        resp.raise_for_status()
        data = resp.json()
        blocks.extend(data.get("results", []))
        url = data.get("next_cursor")
        if url:
            url = f"{NOTION_API}/blocks/{block_id}/children?page_size={page_size}&start_cursor={url}"
        else:
            url = None
    return blocks


def query_database(token: str, db_id: str, page_size: int = 100) -> List[dict]:
    """Query all rows in a database."""
    rows = []
    payload: dict = {"page_size": page_size}
    while True:
        resp = requests.post(
            f"{NOTION_API}/databases/{db_id}/query",
            headers=_headers(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("results", []))
        if data.get("has_more") and data.get("next_cursor"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return rows


def blocks_to_text(blocks: List[dict]) -> str:
    """Convert Notion blocks to plain text."""
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        bdata = block.get(btype, {})

        # Extract rich text
        rich_texts = bdata.get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_texts)

        if btype.startswith("heading"):
            level = btype[-1]  # heading_1 -> 1
            lines.append(f"{'#' * int(level)} {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            checked = "x" if bdata.get("checked") else " "
            lines.append(f"[{checked}] {text}")
        elif btype == "toggle":
            lines.append(f"> {text}")
        elif btype == "code":
            lang = bdata.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype == "divider":
            lines.append("---")
        elif text:
            lines.append(text)

    return "\n".join(lines)


def extract_page_title(page: dict) -> str:
    """Extract title from a page result."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(
                t.get("plain_text", "") for t in prop.get("title", [])
            )
    return "(untitled)"


def extract_property_text(prop: dict) -> str:
    """Extract text value from any property type."""
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    elif ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    elif ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    elif ptype == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    elif ptype == "number":
        return str(prop.get("number", ""))
    elif ptype == "checkbox":
        return str(prop.get("checkbox", False))
    elif ptype == "date":
        d = prop.get("date")
        return d.get("start", "") if d else ""
    elif ptype == "url":
        return prop.get("url", "") or ""
    elif ptype == "status":
        s = prop.get("status")
        return s.get("name", "") if s else ""
    return str(prop)


if __name__ == "__main__":
    import sys
    token = os.getenv("NOTION_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not token:
        print("Usage: python notion_reader.py <token>  OR set NOTION_TOKEN env var")
        sys.exit(1)

    print("Searching all connected content...")
    results = search(token, "", page_size=25)
    print(f"Found {len(results)} items:\n")
    for r in results:
        rtype = r.get("object", "")
        title = extract_page_title(r) if rtype == "page" else r.get("title", [{}])[0].get("plain_text", "(db)") if r.get("title") else "(untitled db)"
        print(f"  [{rtype}] {title}  ({r['id']})")
