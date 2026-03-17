"""Thin wrapper around Anthropic API for structured JSON output."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

import anthropic
from dotenv import load_dotenv

load_dotenv()

_DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from LLM output."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Find the outermost { ... } block
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response:\n{text[:300]}")

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    break

    raise ValueError(f"Failed to parse JSON from response:\n{text[:500]}")


def ask_json(
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """Send a prompt and parse the response as JSON.

    Embeds JSON instruction in user message for maximum compatibility with proxies.
    """
    client = get_client()

    # Embed system context and JSON requirement directly in user message
    # to work around proxies that may strip/ignore system prompts
    combined_user = f"""<instructions>
{system}
</instructions>

{user}

IMPORTANT: Respond with ONLY a JSON object. No explanation, no markdown formatting, no text before or after. Just the raw JSON starting with {{ and ending with }}."""

    resp = client.messages.create(
        model=model or _DEFAULT_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": combined_user}],
    )
    return _extract_json(resp.content[0].text)


def ask_text(
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 1024,
) -> str:
    """Send a prompt and return raw text."""
    client = get_client()

    # Same strategy: embed system in user message for proxy compatibility
    combined_user = f"""<instructions>
{system}
</instructions>

{user}"""

    resp = client.messages.create(
        model=model or _DEFAULT_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": combined_user}],
    )
    return resp.content[0].text.strip()


def ask_structured(
    system: str,
    user: str,
    *,
    schema: Dict[str, Any],
    schema_name: str = "structured_output",
    model: str | None = None,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """Send a prompt and get structured output via Anthropic tool_use.

    Uses tool_use with tool_choice to force schema-matching response.
    Falls back to ask_json if tool_use is unavailable.
    """
    client = get_client()

    tool_def = {
        "name": schema_name,
        "description": f"Output structured data matching the {schema_name} schema.",
        "input_schema": schema,
    }

    combined_user = f"""<instructions>
{system}
</instructions>

{user}"""

    try:
        resp = client.messages.create(
            model=model or _DEFAULT_MODEL,
            max_tokens=max_tokens,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": schema_name},
            messages=[{"role": "user", "content": combined_user}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        raise RuntimeError("No tool_use block in response despite forced tool_choice")
    except (anthropic.BadRequestError, anthropic.APIStatusError, RuntimeError) as exc:
        import logging
        logging.getLogger(__name__).warning("tool_use failed (%s), falling back to ask_json", exc)
        return ask_json(system, user, model=model, max_tokens=max_tokens)
