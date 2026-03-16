"""Tests for default infrastructure wiring."""

from twin_runtime.domain.ports.llm_port import LLMPort


class TestDefaultLLM:
    def test_implements_protocol(self):
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()
        assert isinstance(llm, LLMPort)

    def test_has_ask_json(self):
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()
        assert callable(llm.ask_json)

    def test_has_ask_text(self):
        from twin_runtime.interfaces.defaults import DefaultLLM
        llm = DefaultLLM()
        assert callable(llm.ask_text)
