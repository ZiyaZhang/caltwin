"""Tests that pipeline stages accept injected LLM and don't import infrastructure."""

import ast
import inspect
from pathlib import Path

from twin_runtime.domain.ports.llm_port import LLMPort


class TestNoInfrastructureImports:
    """Verify application/ pipeline files don't import from infrastructure/ at module level."""

    def _get_imports(self, filepath: str) -> list[str]:
        source = Path(filepath).read_text()
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
        return imports

    def test_situation_interpreter_no_infra(self):
        path = "src/twin_runtime/application/pipeline/situation_interpreter.py"
        imports = self._get_imports(path)
        infra = [i for i in imports if "infrastructure" in i]
        assert infra == [], f"Direct infrastructure imports found: {infra}"

    def test_head_activator_no_infra(self):
        path = "src/twin_runtime/application/pipeline/head_activator.py"
        imports = self._get_imports(path)
        infra = [i for i in imports if "infrastructure" in i]
        assert infra == [], f"Direct infrastructure imports found: {infra}"

    def test_decision_synthesizer_no_infra(self):
        path = "src/twin_runtime/application/pipeline/decision_synthesizer.py"
        imports = self._get_imports(path)
        infra = [i for i in imports if "infrastructure" in i]
        assert infra == [], f"Direct infrastructure imports found: {infra}"


class TestLLMInjection:
    def test_interpret_situation_accepts_llm(self):
        from twin_runtime.application.pipeline.situation_interpreter import interpret_situation
        sig = inspect.signature(interpret_situation)
        assert "llm" in sig.parameters

    def test_activate_heads_accepts_llm(self):
        from twin_runtime.application.pipeline.head_activator import activate_heads
        sig = inspect.signature(activate_heads)
        assert "llm" in sig.parameters

    def test_synthesize_accepts_llm(self):
        from twin_runtime.application.pipeline.decision_synthesizer import synthesize
        sig = inspect.signature(synthesize)
        assert "llm" in sig.parameters
