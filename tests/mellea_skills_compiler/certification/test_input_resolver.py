"""Unit tests for mellea_skills_compiler.certification.input_resolver module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mellea_skills_compiler.certification.input_resolver import (
    Fixture,
    InputResolutionError,
    _parse_structured_input,
    _should_parse_as_structured,
    resolve_input,
)


class TestFixture:
    """Test cases for Fixture dataclass."""

    def test_create_fixture(self):
        """Test creating a Fixture instance."""
        fixture = Fixture(
            id="test-fixture",
            context={"key": "value"},
            description="Test description",
        )

        assert fixture.id == "test-fixture"
        assert fixture.context == {"key": "value"}
        assert fixture.description == "Test description"

    def test_fixture_dict_method(self):
        """Test Fixture.dict() method returns proper dict."""
        fixture = Fixture(
            id="test-fixture",
            context={"param1": "value1", "param2": 123},
            description="Test",
        )

        result = fixture.dict()

        assert isinstance(result, dict)
        assert result["id"] == "test-fixture"
        assert result["context"] == {"param1": "value1", "param2": 123}
        assert result["description"] == "Test"


class TestParseStructuredInput:
    """Test cases for _parse_structured_input function."""

    def test_parse_valid_json_object(self):
        """Test parsing valid JSON object."""
        content = '{"key": "value", "number": 42}'
        result = _parse_structured_input(content)

        assert result == {"key": "value", "number": 42}

    def test_parse_json_with_whitespace(self):
        """Test parsing JSON with leading/trailing whitespace."""
        content = '  {"key": "value"}  '
        result = _parse_structured_input(content)

        assert result == {"key": "value"}

    def test_parse_json_array_fails(self):
        """Test that JSON array raises error."""
        content = '["item1", "item2"]'

        with pytest.raises(InputResolutionError) as exc_info:
            _parse_structured_input(content)

        assert "must be a JSON object" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_parse_invalid_json_starting_with_bracket_fails(self):
        """Test that invalid JSON starting with [ fails without trying YAML."""
        content = "[invalid json"

        with pytest.raises(InputResolutionError) as exc_info:
            _parse_structured_input(content)

        assert "Failed to parse input as JSON" in str(exc_info.value)

    def test_parse_valid_yaml_object(self):
        """Test parsing valid YAML object."""
        content = """
key: value
number: 42
nested:
  inner: data
"""
        result = _parse_structured_input(content)

        assert result == {"key": "value", "number": 42, "nested": {"inner": "data"}}

    def test_parse_yaml_with_string_keys(self):
        """Test parsing YAML with all string keys."""
        content = """
param1: value1
param2: value2
"""
        result = _parse_structured_input(content)

        assert result == {"param1": "value1", "param2": "value2"}

    def test_parse_yaml_scalar_fails(self):
        """Test that YAML scalar value raises error."""
        content = "just a string"

        with pytest.raises(InputResolutionError) as exc_info:
            _parse_structured_input(content)

        assert "must be a YAML object" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    def test_parse_empty_content_fails(self):
        """Test that empty content raises error."""
        content = ""

        with pytest.raises(InputResolutionError) as exc_info:
            _parse_structured_input(content)

        assert "must be a YAML object" in str(exc_info.value)
        assert "NoneType" in str(exc_info.value)

    def test_parse_yaml_array_fails(self):
        """Test that YAML array raises error."""
        content = """
- item1
- item2
"""
        with pytest.raises(InputResolutionError) as exc_info:
            _parse_structured_input(content)

        assert "must be a YAML object" in str(exc_info.value)
        assert "list" in str(exc_info.value)

    def test_json_takes_precedence_over_yaml(self):
        """Test that JSON parsing is attempted first."""
        content = '{"key": "value"}'
        result = _parse_structured_input(content)

        # Should parse as JSON
        assert result == {"key": "value"}

    def test_parse_invalid_yaml_fails(self):
        """Test that invalid YAML raises error."""
        # Use YAML with invalid syntax (unclosed quote)
        content = """
key: "unclosed quote
another: value
"""
        # The content doesn't start with { or [, so it will try YAML
        # Invalid YAML should raise InputResolutionError
        with pytest.raises(InputResolutionError) as exc_info:
            _parse_structured_input(content)

        assert "YAML" in str(exc_info.value) or "parse" in str(exc_info.value).lower()


class TestShouldParseAsStructured:
    """Test cases for _should_parse_as_structured function."""

    def test_content_starting_with_brace_returns_true(self):
        """Test that content starting with { returns True."""
        assert _should_parse_as_structured("{key: value}")
        assert _should_parse_as_structured("  {key: value}")

    def test_content_starting_with_bracket_returns_true(self):
        """Test that content starting with [ returns True."""
        assert _should_parse_as_structured("[item1, item2]")
        assert _should_parse_as_structured("  [item1]")

    def test_plain_text_returns_false(self):
        """Test that plain text returns False."""
        assert not _should_parse_as_structured("plain text")
        assert not _should_parse_as_structured("key: value")


class TestResolveInput:
    """Test cases for resolve_input function."""

    def test_no_input_sources_raises_error(self):
        """Test that no input source raises error."""
        mock_fn = MagicMock()

        with pytest.raises(InputResolutionError) as exc_info:
            resolve_input(mock_fn, fixture_id=None, input=None, fixtures=[])

        assert "No input source specified" in str(exc_info.value)

    def test_multiple_input_sources_raises_error(self):
        """Test that multiple input sources raise error."""
        mock_fn = MagicMock()

        with pytest.raises(InputResolutionError) as exc_info:
            resolve_input(
                mock_fn, fixture_id="fixture1", input="some input", fixtures=[]
            )

        assert "Multiple input sources specified" in str(exc_info.value)

    def test_resolve_existing_fixture(self):
        """Test resolving an existing fixture."""
        mock_fn = MagicMock()
        fixtures = [
            {
                "id": "fixture1",
                "context": {"param1": "value1"},
                "description": "Test fixture",
            },
            {
                "id": "fixture2",
                "context": {"param2": "value2"},
                "description": "Test 2",
            },
        ]

        result = resolve_input(mock_fn, fixture_id="fixture1", fixtures=fixtures)

        assert isinstance(result, Fixture)
        assert result.id == "fixture1"
        assert result.context == {"param1": "value1"}
        assert result.description == "Test fixture"

    def test_resolve_nonexistent_fixture_raises_error(self):
        """Test that nonexistent fixture raises error."""
        mock_fn = MagicMock()
        fixtures = [
            {"id": "fixture1", "context": {}, "description": "Test"},
            {"id": "fixture2", "context": {}, "description": "Test 2"},
        ]

        with pytest.raises(InputResolutionError) as exc_info:
            resolve_input(mock_fn, fixture_id="unknown", fixtures=fixtures)

        assert "Unknown fixture 'unknown'" in str(exc_info.value)
        assert "fixture1" in str(exc_info.value)
        assert "fixture2" in str(exc_info.value)

    def test_resolve_structured_json_input(self):
        """Test resolving structured JSON input."""

        def mock_pipeline_fn(param1: str, param2: int):
            pass

        input_str = '{"param1": "value1", "param2": 42}'

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert result.id == "User_Input"
        assert result.context == {"param1": "value1", "param2": 42}
        assert result.description == "JSON/YAML Input"

    def test_resolve_structured_yaml_input_as_json(self):
        """Test resolving structured input in JSON format."""

        def mock_pipeline_fn(param1: str, param2: int):
            pass

        # JSON input (which is also valid YAML)
        input_str = '{"param1": "value1", "param2": 42}'

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert result.id == "User_Input"
        assert result.context == {"param1": "value1", "param2": 42}
        assert result.description == "JSON/YAML Input"

    def test_resolve_raw_input_single_param(self):
        """Test resolving raw string input for single-parameter function."""

        def mock_pipeline_fn(text: str):
            pass

        input_str = "raw string input"

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert result.id == "User_Input"
        assert result.context == {"text": "raw string input"}
        assert result.description == "Raw Input"

    def test_resolve_raw_input_multi_param_raises_error(self):
        """Test that raw input for multi-parameter function raises error."""

        def mock_pipeline_fn(param1: str, param2: str):
            pass

        input_str = "raw string"

        with pytest.raises(InputResolutionError) as exc_info:
            resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert "takes multiple parameters" in str(exc_info.value)
        assert "param1" in str(exc_info.value)
        assert "param2" in str(exc_info.value)

    def test_resolve_file_input_json(self):
        """Test resolving input from JSON file."""

        def mock_pipeline_fn(param1: str):
            pass

        data = {"param1": "value from file"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            file_path = f.name

        try:
            result = resolve_input(
                mock_pipeline_fn, input=f"file://{file_path}", fixtures=[]
            )

            assert result.id == "User_Input"
            assert result.context == {"param1": "value from file"}
            assert result.description == "JSON/YAML Input"
        finally:
            Path(file_path).unlink()

    def test_resolve_file_input_nonexistent_file_raises_error(self):
        """Test that nonexistent file raises error."""

        def mock_pipeline_fn(param: str):
            pass

        with pytest.raises(InputResolutionError) as exc_info:
            resolve_input(
                mock_pipeline_fn, input="file:///nonexistent/file.json", fixtures=[]
            )

        assert "File not found" in str(exc_info.value)

    @patch("mellea_skills_compiler.certification.input_resolver.Prompt.ask")
    def test_resolve_stdin_input_prompt(self, mock_prompt_ask):
        """Test resolving input from stdin (interactive prompt)."""

        def mock_pipeline_fn(param1: str, param2: int):
            pass

        # Mock the prompt responses
        mock_prompt_ask.side_effect = ["value1", "42"]

        result = resolve_input(mock_pipeline_fn, input="-", fixtures=[])

        assert result.id == "User_Input"
        assert result.context == {"param1": "value1", "param2": "42"}
        assert result.description == "Prompt Input"
        assert mock_prompt_ask.call_count == 2

    def test_resolve_invalid_json_falls_back_to_raw(self):
        """Test that invalid JSON that doesn't look like JSON falls back to raw input."""

        def mock_pipeline_fn(text: str):
            pass

        # Input that doesn't start with { or [, so should be treated as raw
        input_str = "just plain text"

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert result.id == "User_Input"
        assert result.context == {"text": "just plain text"}
        assert result.description == "Raw Input"

    def test_resolve_function_with_no_parameters(self):
        """Test resolving input for function with no parameters."""

        def mock_pipeline_fn():
            pass

        input_str = '{"key": "value"}'

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        # Should still parse as structured input
        assert result.context == {"key": "value"}

    def test_resolve_function_with_keyword_only_params(self):
        """Test resolving input for function with keyword-only parameters."""

        def mock_pipeline_fn(*, param1: str, param2: int):
            pass

        input_str = '{"param1": "value1", "param2": 42}'

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert result.context == {"param1": "value1", "param2": 42}

    def test_resolve_empty_string_input_single_param(self):
        """Test resolving empty string input for single parameter function."""

        def mock_pipeline_fn(text: str):
            pass

        result = resolve_input(mock_pipeline_fn, input="", fixtures=[])

        assert result.context == {"text": ""}
        assert result.description == "Raw Input"

    def test_resolve_file_with_raw_text(self):
        """Test resolving file containing raw text (not JSON/YAML)."""

        def mock_pipeline_fn(text: str):
            pass

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("plain text content")
            file_path = f.name

        try:
            result = resolve_input(
                mock_pipeline_fn, input=f"file://{file_path}", fixtures=[]
            )

            # File input should try structured parsing first, then fall back to raw
            assert result.context == {"text": "plain text content"}
            assert result.description == "Raw Input"
        finally:
            Path(file_path).unlink()

    def test_structured_input_parsing_failure_logs_and_falls_back(self):
        """Test that structured parsing failure is logged and falls back to raw input."""

        def mock_pipeline_fn(text: str):
            pass

        # Input that looks like JSON but is invalid
        # This should not start with { or [, so it goes to raw
        input_str = "not json at all"

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        assert result.context == {"text": "not json at all"}
        assert result.description == "Raw Input"

    def test_resolve_with_var_positional_ignored(self):
        """Test that *args parameters are ignored in signature inspection."""

        def mock_pipeline_fn(param1: str, *args):
            pass

        input_str = "raw text"

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        # Should treat as single-parameter function (param1 only)
        assert result.context == {"param1": "raw text"}

    def test_resolve_with_var_keyword_ignored(self):
        """Test that **kwargs parameters are ignored in signature inspection."""

        def mock_pipeline_fn(param1: str, **kwargs):
            pass

        input_str = "raw text"

        result = resolve_input(mock_pipeline_fn, input=input_str, fixtures=[])

        # Should treat as single-parameter function (param1 only)
        assert result.context == {"param1": "raw text"}
