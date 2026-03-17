"""Tests for LLMPort.ask_structured via tool_use."""
import pytest
from unittest.mock import MagicMock, patch
from twin_runtime.interfaces.defaults import DefaultLLM
from twin_runtime.domain.ports.llm_port import LLMPort


class TestAskStructured:
    def test_protocol_has_ask_structured(self):
        llm = DefaultLLM()
        assert hasattr(llm, "ask_structured")

    def test_implements_protocol(self):
        llm = DefaultLLM()
        assert isinstance(llm, LLMPort)

    def test_ask_structured_returns_dict(self):
        schema = {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "option_ranking": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["confidence", "option_ranking"],
        }
        expected = {"confidence": 0.8, "option_ranking": ["A", "B"]}

        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "tool_use"
        mock_content.input = expected
        mock_response.content = [mock_content]
        mock_response.stop_reason = "tool_use"

        with patch("twin_runtime.infrastructure.llm.client.get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_get.return_value = mock_client
            llm = DefaultLLM()
            result = llm.ask_structured("system msg", "user msg", schema=schema, schema_name="test_output")
            assert result == expected

    def test_ask_structured_fallback_to_ask_json(self):
        schema = {
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
        }

        with patch("twin_runtime.infrastructure.llm.client.get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = RuntimeError("tool_use not supported")
            mock_get.return_value = mock_client

            with patch("twin_runtime.infrastructure.llm.client.ask_json") as mock_ask_json:
                mock_ask_json.return_value = {"value": 42}
                llm = DefaultLLM()
                result = llm.ask_structured("sys", "usr", schema=schema, schema_name="test")
                assert result == {"value": 42}
                mock_ask_json.assert_called_once()
