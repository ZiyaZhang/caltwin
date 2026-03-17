"""MCP Server for twin-runtime: exposes twin_decide, twin_status, twin_reflect as tools.

Uses the `mcp` SDK when available (Python >= 3.10), otherwise falls back to a
minimal JSON-RPC/stdio implementation that speaks the MCP protocol directly.
"""
from __future__ import annotations

import json
import asyncio
import sys
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Tool definitions (shared by both SDK and fallback paths)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "twin_decide",
        "description": "Run your calibrated judgment twin on a decision scenario",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The decision context/question"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Options to evaluate",
                },
            },
            "required": ["query", "options"],
        },
    },
    {
        "name": "twin_status",
        "description": "Show twin state — domains, reliability, known biases, fidelity summary",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "twin_reflect",
        "description": "Record what you actually chose — feeds the calibration loop",
        "inputSchema": {
            "type": "object",
            "properties": {
                "choice": {"type": "string", "description": "What was actually chosen"},
                "reasoning": {"type": "string", "description": "Why this was chosen"},
                "trace_id": {"type": "string", "description": "Link to a previous twin_decide trace"},
                "feedback_target": {
                    "type": "string",
                    "enum": ["choice", "reasoning", "confidence"],
                    "description": "Where the twin was off",
                },
            },
            "required": ["choice"],
        },
    },
    {
        "name": "twin_calibrate",
        "description": "Run batch fidelity evaluation on calibration cases",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "twin_history",
        "description": "List recent decision traces",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of traces to return",
                    "default": 10,
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Shared infrastructure helpers
# ---------------------------------------------------------------------------

def _get_stores():
    """Return (TwinStore, TraceStore, CalibrationStore, EvidenceStore, user_id) from env config."""
    from twin_runtime.infrastructure.backends.json_file.twin_store import TwinStore
    from twin_runtime.infrastructure.backends.json_file.trace_store import JsonFileTraceStore as TraceStore
    from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
    from twin_runtime.infrastructure.backends.json_file.evidence_store import JsonFileEvidenceStore
    from pathlib import Path
    import os

    store_dir = os.getenv("TWIN_STORE_DIR", str(Path.home() / ".twin-runtime" / "store"))
    user_id = os.getenv("TWIN_USER_ID", "default")

    twin_store = TwinStore(store_dir)
    trace_store = TraceStore(Path(store_dir) / user_id / "traces")
    cal_store = CalibrationStore(store_dir, user_id)
    evidence_store = JsonFileEvidenceStore(Path(store_dir) / user_id / "evidence")

    return twin_store, trace_store, cal_store, evidence_store, user_id


def _load_twin(twin_store, user_id):
    """Load twin state from store. Returns None if not found (fail-closed)."""
    from twin_runtime.domain.models.twin_state import TwinState
    if twin_store.has_current(user_id):
        return twin_store.load_state(user_id)
    return None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def _handle_decide(args: Dict[str, Any]) -> str:
    """Run the twin pipeline on a decision and persist the trace."""
    query = args.get("query", "")
    options = args.get("options", [])

    if not query or not options:
        return json.dumps({"error": "'query' and 'options' are required."})

    try:
        from twin_runtime.application.pipeline.runner import run

        twin_store, trace_store, _, evidence_store, user_id = _get_stores()
        twin = _load_twin(twin_store, user_id)
        if twin is None:
            return json.dumps({"error": "No twin state found. Run 'twin-runtime init' first."})

        trace = run(query=query, option_set=options, twin=twin, evidence_store=evidence_store)

        # Persist trace so twin_reflect can load it later
        trace_store.save_trace(trace)

        result = {
            "decision": trace.final_decision,
            "mode": trace.decision_mode.value,
            "uncertainty": trace.uncertainty,
            "activated_domains": [d.value for d in trace.activated_domains],
            "trace_id": trace.trace_id,
            "reasoning": trace.output_text,
        }
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "Error running twin_decide: %s" % e})


async def _handle_status(args: Dict[str, Any]) -> str:
    """Show twin status."""
    try:
        twin_store, _, _, _, user_id = _get_stores()
        twin = _load_twin(twin_store, user_id)
        if twin is None:
            return json.dumps({"error": "No twin state found. Run 'twin-runtime init' first."})

        domains = []
        for h in twin.domain_heads:
            domains.append({
                "domain": h.domain.value,
                "reliability": h.head_reliability,
                "goal_axes": h.goal_axes,
                "keywords": h.keywords[:5] if h.keywords else [],
            })

        status = {
            "version": twin.state_version,
            "user_id": twin.user_id,
            "domains": domains,
            "biases_active": sum(1 for b in twin.bias_correction_policy if b.still_active),
            "core_confidence": twin.shared_decision_core.core_confidence,
            "scope": {
                "valid_domains": [d.value for d in twin.valid_domains()],
                "min_reliability": twin.scope_declaration.min_reliability_threshold,
            },
        }
        return json.dumps(status, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def _handle_reflect(args: Dict[str, Any]) -> str:
    """Record an outcome, persisting to CalibrationStore."""
    choice = args.get("choice", "")
    reasoning = args.get("reasoning")
    trace_id = args.get("trace_id")
    feedback_target = args.get("feedback_target")

    if not choice:
        return json.dumps({"error": "'choice' is required."})

    try:
        from twin_runtime.domain.models.primitives import OutcomeSource

        twin_store, trace_store, cal_store, _, user_id = _get_stores()
        twin = _load_twin(twin_store, user_id)

        result = {
            "status": "recorded",
            "choice": choice,
            "reasoning": reasoning,
            "trace_id": trace_id or "manual",
            "feedback_target": feedback_target,
        }

        if trace_id and twin:
            # Full path: load trace, compute similarity, save outcome
            try:
                from twin_runtime.application.calibration.outcome_tracker import record_outcome
                outcome, update = record_outcome(
                    trace_id=trace_id,
                    actual_choice=choice,
                    source=OutcomeSource.USER_REFLECTION,
                    actual_reasoning=reasoning,
                    twin=twin,
                    trace_store=trace_store,
                    calibration_store=cal_store,
                )
                result["outcome_id"] = outcome.outcome_id
                result["prediction_rank"] = outcome.prediction_rank
                result["calibration_updated"] = update is not None
                result["message"] = "Outcome recorded and linked to trace. Calibration updated."
            except FileNotFoundError:
                # Trace not found — fall through to standalone recording
                result["message"] = "Trace not found, recording as standalone outcome."
                _save_standalone_outcome(cal_store, choice, reasoning, trace_id, user_id)
        else:
            # No trace_id — standalone outcome recording
            _save_standalone_outcome(cal_store, choice, reasoning, trace_id, user_id)
            result["message"] = "Outcome recorded (standalone). Use trace_id for full calibration."

        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "Error recording outcome: %s" % e})


def _save_standalone_outcome(cal_store, choice, reasoning, trace_id, user_id):
    """Save an OutcomeRecord without a linked trace."""
    import uuid
    from datetime import datetime, timezone
    from twin_runtime.domain.models.calibration import OutcomeRecord
    from twin_runtime.domain.models.primitives import OutcomeSource, DomainEnum

    # USER_REFLECTION requires reasoning; use OBSERVED for bare outcomes
    source = OutcomeSource.USER_REFLECTION if reasoning else OutcomeSource.OBSERVED

    outcome = OutcomeRecord(
        outcome_id=str(uuid.uuid4()),
        trace_id=trace_id or "manual",
        user_id=user_id,
        actual_choice=choice,
        actual_reasoning=reasoning,
        outcome_source=source,
        prediction_rank=None,
        confidence_at_prediction=0.5,
        domain=DomainEnum.WORK,
        created_at=datetime.now(timezone.utc),
    )
    cal_store.save_outcome(outcome)


async def _handle_calibrate(args: Dict[str, Any]) -> str:
    """Run batch fidelity evaluation."""
    try:
        from twin_runtime.infrastructure.backends.json_file.calibration_store import CalibrationStore
        from twin_runtime.application.calibration.fidelity_evaluator import evaluate_fidelity

        twin_store, _, cal_store, _, user_id = _get_stores()
        twin = _load_twin(twin_store, user_id)
        if twin is None:
            return json.dumps({"error": "No twin state found. Run 'twin-runtime init' first."})

        cases = cal_store.list_cases(used=None)
        if not cases:
            return json.dumps({"message": "No calibration cases found.", "choice_similarity": 0.0})

        evaluation = evaluate_fidelity(cases, twin)
        cal_store.save_evaluation(evaluation)

        result = {
            "evaluation_id": evaluation.evaluation_id,
            "choice_similarity": evaluation.choice_similarity,
            "reasoning_similarity": evaluation.reasoning_similarity,
            "domain_reliability": evaluation.domain_reliability,
            "total_cases": len(cases),
            "failed_cases": evaluation.failed_case_count,
        }
        if evaluation.abstention_accuracy is not None:
            result["abstention_accuracy"] = evaluation.abstention_accuracy
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "Error running calibrate: %s" % e})


async def _handle_history(args: Dict[str, Any]) -> str:
    """List recent decision traces."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 100))
    try:
        _, trace_store, _, _, user_id = _get_stores()

        traces = []
        trace_dir = trace_store.base
        if trace_dir.exists():
            files = sorted(trace_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[:limit]:
                try:
                    from twin_runtime.domain.models.runtime import RuntimeDecisionTrace
                    trace = RuntimeDecisionTrace.model_validate_json(f.read_text())
                    traces.append({
                        "trace_id": trace.trace_id,
                        "decision": trace.final_decision,
                        "mode": trace.decision_mode.value,
                        "uncertainty": trace.uncertainty,
                        "domains": [d.value for d in trace.activated_domains],
                        "created_at": trace.created_at.isoformat(),
                    })
                except Exception:
                    continue

        return json.dumps({"traces": traces, "count": len(traces)}, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "Error listing history: %s" % e})


_TOOL_HANDLERS = {
    "twin_decide": _handle_decide,
    "twin_status": _handle_status,
    "twin_reflect": _handle_reflect,
    "twin_calibrate": _handle_calibrate,
    "twin_history": _handle_history,
}


# ---------------------------------------------------------------------------
# Try SDK-based server first, fall back to raw JSON-RPC
# ---------------------------------------------------------------------------

_HAS_MCP_SDK = False
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    _HAS_MCP_SDK = True
except ImportError:
    pass


def create_server():
    """Create and configure the twin-runtime MCP server.

    Returns an SDK Server if the `mcp` package is available, otherwise
    returns a _StdioMCPServer that speaks the protocol directly.
    """
    if _HAS_MCP_SDK:
        return _create_sdk_server()
    return _StdioMCPServer()


# ---------------------------------------------------------------------------
# SDK path
# ---------------------------------------------------------------------------

def _create_sdk_server():
    """Build server using the mcp SDK."""
    server = Server("twin-runtime")

    @server.list_tools()
    async def list_tools() -> list:
        return [Tool(**t) for t in TOOLS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text="Unknown tool: %s" % name)]
        text = await handler(arguments)
        return [TextContent(type="text", text=text)]

    return server


# ---------------------------------------------------------------------------
# Fallback: minimal JSON-RPC / MCP over stdio
# ---------------------------------------------------------------------------

class _StdioMCPServer:
    """Minimal MCP server that reads JSON-RPC from stdin and writes to stdout.

    Implements just enough of the MCP protocol for tool listing and calling.
    """

    SERVER_INFO = {
        "name": "twin-runtime",
        "version": "0.1.0",
    }

    CAPABILITIES = {
        "tools": {},
    }

    # -- public interface (matches how we call the SDK server) --

    async def run_forever(self):
        """Read JSON-RPC messages from stdin, dispatch, respond on stdout."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        # We accumulate bytes and split on newlines (ndjson transport).
        buf = b""
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                response = await self._dispatch(msg)
                if response is not None:
                    self._write(response)

    # -- internals --

    def _write(self, obj: dict):
        raw = json.dumps(obj, ensure_ascii=False) + "\n"
        sys.stdout.write(raw)
        sys.stdout.flush()

    async def _dispatch(self, msg: dict) -> Optional[dict]:
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        # Notifications (no id) — we just acknowledge
        if msg_id is None:
            if method == "notifications/initialized":
                return None
            return None

        if method == "initialize":
            return self._result(msg_id, {
                "protocolVersion": "2024-11-05",
                "serverInfo": self.SERVER_INFO,
                "capabilities": self.CAPABILITIES,
            })

        if method == "tools/list":
            return self._result(msg_id, {"tools": TOOLS})

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            handler = _TOOL_HANDLERS.get(tool_name)
            if handler is None:
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": "Unknown tool: %s" % tool_name}],
                    "isError": True,
                })
            try:
                text = await handler(arguments)
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": text}],
                })
            except Exception as e:
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": "Error: %s" % e}],
                    "isError": True,
                })

        if method == "ping":
            return self._result(msg_id, {})

        # Unknown method
        return self._error(msg_id, -32601, "Method not found: %s" % method)

    @staticmethod
    def _result(msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_server():
    """Run the MCP server on stdio."""
    server = create_server()
    if _HAS_MCP_SDK:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    else:
        await server.run_forever()
