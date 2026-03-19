"""Setup commands: cmd_init, cmd_config, cmd_sources."""

from __future__ import annotations

import json

from twin_runtime.cli._main import (
    _CONFIG_DIR,
    _CONFIG_FILE,
    _STORE_DIR,
    _build_registry,
    _load_config,
    _mask,
    _save_config,
    _write_env,
)
from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
from twin_runtime.domain.models.twin_state import TwinState


def cmd_init(args):
    """Interactive setup."""
    print("=== Twin Runtime Setup ===\n")
    config = _load_config()

    # User ID
    user_id = input(f"User ID [{config.get('user_id', 'user-default')}]: ").strip()
    if user_id:
        config["user_id"] = user_id
    elif "user_id" not in config:
        config["user_id"] = "user-default"

    # LLM API
    print("\n--- LLM API Configuration ---")
    api_key = input(f"Anthropic API Key [{_mask(config.get('api_key', ''))}]: ").strip()
    if api_key:
        config["api_key"] = api_key

    base_url = input(f"API Base URL [{config.get('api_base_url', 'https://api.anthropic.com')}]: ").strip()
    if base_url:
        config["api_base_url"] = base_url
    elif "api_base_url" not in config:
        config["api_base_url"] = "https://api.anthropic.com"

    model = input(f"Model [{config.get('model', 'claude-sonnet-4-20250514')}]: ").strip()
    if model:
        config["model"] = model
    elif "model" not in config:
        config["model"] = "claude-sonnet-4-20250514"

    # Sources
    print("\n--- Data Sources ---")

    # OpenClaw
    openclaw_path = input(f"OpenClaw workspace path [{config.get('openclaw_path', '')}]: ").strip()
    if openclaw_path:
        config["openclaw_path"] = openclaw_path

    # Notion
    notion_token = input(f"Notion API token [{_mask(config.get('notion_token', ''))}]: ").strip()
    if notion_token:
        config["notion_token"] = notion_token

    # Google
    google_creds = input(f"Google credentials.json path [{config.get('google_credentials', '')}]: ").strip()
    if google_creds:
        config["google_credentials"] = google_creds

    # Twin state fixture
    fixture = input(f"Initial TwinState fixture [{config.get('fixture_path', '')}]: ").strip()
    if fixture:
        config["fixture_path"] = fixture

    _save_config(config)
    _write_env(config)

    print(f"\nConfig saved to {_CONFIG_FILE}")
    print(f"Environment written to {_CONFIG_DIR / '.env'}")

    # Load/create initial twin state if fixture provided
    if config.get("fixture_path"):
        store = TwinStore(str(_STORE_DIR))
        if not store.has_current(config["user_id"]):
            try:
                with open(config["fixture_path"]) as f:
                    twin = TwinState(**json.load(f))
                store.save_state(twin)
                print(f"Twin state initialized: {twin.state_version}")
            except Exception as e:
                print(f"Warning: could not load fixture: {e}")

    print("\nSetup complete! Try: twin-runtime status")


def cmd_config(args):
    """Get/set configuration."""
    config = _load_config()
    if args.action == "set":
        if not args.key or not args.value:
            print("Usage: twin-runtime config set <key> <value>")
            return
        config[args.key] = args.value
        _save_config(config)
        _write_env(config)
        print(f"Set {args.key} = {_mask(args.value) if 'key' in args.key.lower() or 'token' in args.key.lower() else args.value}")
    elif args.action == "get":
        if not args.key:
            print("Usage: twin-runtime config get <key>")
            return
        val = config.get(args.key, "(not set)")
        print(f"{args.key} = {_mask(val) if 'key' in args.key.lower() or 'token' in args.key.lower() else val}")
    elif args.action == "list":
        for k, v in sorted(config.items()):
            display = _mask(v) if ('key' in k.lower() or 'token' in k.lower()) and isinstance(v, str) else v
            print(f"  {k}: {display}")


def cmd_sources(args):
    """List configured data sources."""
    config = _load_config()
    registry = _build_registry(config)

    sources = registry.list_sources()
    if not sources:
        print("No sources configured.")
        return

    status = registry.check_all()
    for name in sources:
        ok = status.get(name, False)
        adapter = registry.get(name)
        meta = adapter.get_source_metadata() if adapter else {}
        print(f"  {'OK' if ok else 'FAIL'} {name}")
        for k, v in meta.items():
            if k != "source_type":
                print(f"       {k}: {v}")
