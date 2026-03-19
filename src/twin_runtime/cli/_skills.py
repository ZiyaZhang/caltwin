"""Skills commands: cmd_install_skills, cmd_mcp_serve."""

from __future__ import annotations

from pathlib import Path


def cmd_install_skills(args):
    """Install Claude Code skills."""
    try:
        from importlib.resources import files
    except ImportError:
        from importlib_resources import files

    if args.personal:
        target = Path.home() / ".claude" / "skills"
    else:
        target = Path.cwd() / ".claude" / "skills"

    target.mkdir(parents=True, exist_ok=True)

    try:
        skills_pkg = files("twin_runtime.resources.skills")
    except (ModuleNotFoundError, TypeError):
        # Fallback: try to find skills relative to this file
        skills_pkg = Path(__file__).parent.parent / "resources" / "skills"
        if not skills_pkg.exists():
            print("Error: skills resources not found. Is twin-runtime installed correctly?")
            return

    installed = []
    for skill_dir in sorted(skills_pkg.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        dest = target / skill_name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        if dest.exists() and not args.force:
            print(f"  SKIP {skill_name} (already exists, use --force to overwrite)")
            continue
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(skill_file.read_text())
        installed.append(skill_name)
        print(f"  OK   {skill_name}")

    print(f"\nInstalled {len(installed)} skills to {target}")


def cmd_mcp_serve(args):
    """Start MCP server (stdio, blocking)."""
    import asyncio
    from twin_runtime.server.mcp_server import run_server
    asyncio.run(run_server())
