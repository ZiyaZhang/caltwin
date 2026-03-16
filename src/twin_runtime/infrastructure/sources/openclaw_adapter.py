"""OpenClaw (Claude Code) workspace adapter.

Reads from:
- CLAUDE.md files (project context, preferences)
- .claude/memory/ files (persistent memories)
- .claude/projects/*/memory/ files (project-specific memories)
- .claude/settings.json (user preferences)
- Conversation transcripts (.jsonl files in .claude/projects/)

Evidence types extracted:
- PREFERENCE: from memory files and CLAUDE.md
- BEHAVIOR: from conversation patterns
- CONTEXT: from project structure and settings
- DECISION: from conversation transcripts where choices were made
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from twin_runtime.domain.evidence.base import EvidenceFragment, SourceAdapter
from twin_runtime.domain.evidence.types import ContextEvidence, PreferenceEvidence, BehaviorEvidence
from twin_runtime.domain.models.primitives import DomainEnum


class OpenClawAdapter(SourceAdapter):
    """Extract evidence from Claude Code / OpenClaw workspace."""

    def __init__(self, workspace_path: str, home_dir: Optional[str] = None):
        self.workspace = Path(workspace_path)
        self.home = Path(home_dir or os.path.expanduser("~"))
        self.claude_dir = self.home / ".claude"

    @property
    def source_type(self) -> str:
        return "openclaw"

    def check_connection(self) -> bool:
        return self.workspace.exists()

    def scan(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        fragments: List[EvidenceFragment] = []
        fragments.extend(self._scan_claude_md())
        fragments.extend(self._scan_memory_files())
        fragments.extend(self._scan_settings())
        fragments.extend(self._scan_transcripts(since))
        return fragments

    def get_source_metadata(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "workspace": str(self.workspace),
            "claude_dir": str(self.claude_dir),
            "has_claude_md": (self.workspace / "CLAUDE.md").exists(),
            "has_memory": (self.claude_dir / "memory").exists(),
        }

    # --- CLAUDE.md ---

    def _scan_claude_md(self) -> List[EvidenceFragment]:
        fragments = []
        # Project-level CLAUDE.md
        for claude_md in self.workspace.rglob("CLAUDE.md"):
            content = claude_md.read_text(errors="ignore")
            if not content.strip():
                continue
            mtime = datetime.fromtimestamp(claude_md.stat().st_mtime, tz=timezone.utc)
            fragments.append(ContextEvidence(
                source_type=self.source_type,
                source_id=str(claude_md),
                occurred_at=mtime,
                valid_from=mtime,
                summary=f"Project instructions from {claude_md.name}",
                raw_excerpt=content[:2000],
                confidence=0.8,
                extraction_method="rule_based",
                user_id="user-default",
                context_category="project_instructions",
                description=f"CLAUDE.md at {claude_md}",
                structured_data={"file": str(claude_md), "type": "claude_md"},
            ))
        return fragments

    # --- Memory files ---

    def _scan_memory_files(self) -> List[EvidenceFragment]:
        fragments = []
        memory_dirs = [
            self.claude_dir / "memory",
        ]
        # Also scan project-specific memory dirs
        projects_dir = self.claude_dir / "projects"
        if projects_dir.exists():
            for proj in projects_dir.iterdir():
                mem_dir = proj / "memory"
                if mem_dir.exists():
                    memory_dirs.append(mem_dir)

        for mem_dir in memory_dirs:
            if not mem_dir.exists():
                continue
            for mem_file in mem_dir.glob("*.md"):
                content = mem_file.read_text(errors="ignore")
                if not content.strip():
                    continue
                mtime = datetime.fromtimestamp(mem_file.stat().st_mtime, tz=timezone.utc)

                # Parse frontmatter if present
                meta = self._parse_memory_frontmatter(content)
                mem_type = meta.get("type", "unknown")

                # Map memory types to evidence classes
                if mem_type == "feedback":
                    fragments.append(PreferenceEvidence(
                        source_type=self.source_type,
                        source_id=str(mem_file),
                        occurred_at=mtime,
                        valid_from=mtime,
                        summary=meta.get("description", f"Memory: {mem_file.stem}"),
                        raw_excerpt=content[:1500],
                        confidence=0.85,
                        extraction_method="rule_based",
                        user_id="user-default",
                        dimension=meta.get("name", mem_file.stem),
                        direction="configured",
                        structured_data={
                            "file": str(mem_file),
                            "memory_type": mem_type,
                            "memory_name": meta.get("name", mem_file.stem),
                        },
                    ))
                else:
                    # user, project, reference -> ContextEvidence
                    fragments.append(ContextEvidence(
                        source_type=self.source_type,
                        source_id=str(mem_file),
                        occurred_at=mtime,
                        valid_from=mtime,
                        summary=meta.get("description", f"Memory: {mem_file.stem}"),
                        raw_excerpt=content[:1500],
                        confidence=0.85,
                        extraction_method="rule_based",
                        user_id="user-default",
                        context_category=mem_type,
                        description=meta.get("description", f"Memory: {mem_file.stem}"),
                        structured_data={
                            "file": str(mem_file),
                            "memory_type": mem_type,
                            "memory_name": meta.get("name", mem_file.stem),
                        },
                    ))
        return fragments

    # --- Settings ---

    def _scan_settings(self) -> List[EvidenceFragment]:
        settings_path = self.claude_dir / "settings.json"
        if not settings_path.exists():
            return []
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

        mtime = datetime.fromtimestamp(settings_path.stat().st_mtime, tz=timezone.utc)
        return [PreferenceEvidence(
            source_type=self.source_type,
            source_id=str(settings_path),
            occurred_at=mtime,
            valid_from=mtime,
            summary="User's Claude Code settings and preferences",
            confidence=0.7,
            extraction_method="api_structured",
            user_id="user-default",
            dimension="tool_settings",
            direction="configured",
            structured_data={"settings": settings},
        )]

    # --- Transcripts ---

    def _scan_transcripts(self, since: Optional[datetime] = None) -> List[EvidenceFragment]:
        """Scan conversation transcripts for decision evidence.

        This is intentionally lightweight -- full transcript analysis
        should be done by the persona compiler with LLM assistance.
        """
        fragments = []
        projects_dir = self.claude_dir / "projects"
        if not projects_dir.exists():
            return []

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            if since and mtime < since:
                continue

            # Don't read full transcript -- just record it exists for later analysis
            file_size = jsonl_file.stat().st_size
            fragments.append(BehaviorEvidence(
                source_type=self.source_type,
                source_id=str(jsonl_file),
                occurred_at=mtime,
                valid_from=mtime,
                summary=f"Conversation transcript ({file_size // 1024}KB)",
                confidence=0.5,
                extraction_method="rule_based",
                user_id="user-default",
                action_type="conversation",
                pattern=f"Transcript {jsonl_file.name}",
                structured_metrics={
                    "file": str(jsonl_file),
                    "size_bytes": file_size,
                    "type": "transcript",
                    "needs_llm_analysis": True,
                },
            ))
        return fragments

    # --- Helpers ---

    @staticmethod
    def _parse_memory_frontmatter(content: str) -> Dict[str, str]:
        """Parse YAML-like frontmatter from memory files."""
        meta: Dict[str, str] = {}
        if not content.startswith("---"):
            return meta
        lines = content.split("\n")
        in_frontmatter = False
        for line in lines:
            if line.strip() == "---":
                if in_frontmatter:
                    break
                in_frontmatter = True
                continue
            if in_frontmatter and ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        return meta
