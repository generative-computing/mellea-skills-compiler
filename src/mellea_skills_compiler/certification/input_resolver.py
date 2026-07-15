"""Input resolution for mellea-skills run command.

Implements Stage 1 of the deep-research recommendations:
- Multi-source input handling (file, raw, stdin, fixture)
- Mutual exclusion checking
- Signature-aware parameter mapping
"""

import inspect
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml
from rich.prompt import Prompt

from mellea_skills_compiler.toolkit.logging import configure_logger


LOGGER = configure_logger()


class InputResolutionError(Exception):
    """Raised when input resolution fails."""

    pass


@dataclass(kw_only=True)
class Fixture:
    id: str
    context: Dict[str, Any]
    description: str

    def dict(self):
        return asdict(self)


def _parse_structured_input(content: str) -> Dict[str, Any]:
    """Parse JSON or YAML content into a dict.

    Returns:
        Parsed dict
    Raises:
        InputResolutionError if parsing fails
    """
    # Try JSON first
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
        raise InputResolutionError(
            f"Structured input must be a JSON object, got {type(parsed).__name__}"
        )
    except json.JSONDecodeError:
        pass

    # Try YAML
    try:
        parsed = yaml.safe_load(content)
        if isinstance(parsed, dict):
            return parsed
        raise InputResolutionError(
            f"Structured input must be a YAML object, got {type(parsed).__name__}"
        )
    except yaml.YAMLError as e:
        raise InputResolutionError(f"Failed to parse input as JSON or YAML: {e}")


def _should_parse_as_structured(content: str) -> bool:
    """Heuristic to determine if content should be parsed as structured data.

    Returns True if content starts with { or [ (likely JSON/YAML object/array).
    """
    stripped = content.strip()
    return stripped.startswith("{") or stripped.startswith("[")


def resolve_input(
    pipeline_fn: Callable,
    fixture_id: Optional[str] = None,
    input: Optional[str] = None,
    fixtures: Optional[list] = None,
) -> Fixture:
    """Resolve input from multiple possible sources.

    Implements Stage 1 mutual exclusion and resolution logic.

    Args:
        pipeline_fn: The pipeline function to run
        fixture_id: Fixture identifier
        input: --input value (may include @file/@- syntax)
        fixtures: List of available fixtures

    Returns:
        ResolvedInput with context dict and metadata

    Raises:
        InputResolutionError on conflicts or resolution failures
    """
    # No input specified
    if fixture_id is None and input is None:
        raise InputResolutionError(
            "No input source specified. Provide one of: --input or --fixture"
        )
    # Mutual exclusion check
    elif fixture_id and input:
        raise InputResolutionError(
            f"Multiple input sources specified. Use exactly one of: --input or --fixture"
        )

    # Resolve fixture
    if fixture_id is not None:
        for f in fixtures:
            if f["id"] == fixture_id:
                return Fixture(**f)
        raise InputResolutionError(
            f"Unknown fixture '{fixture_id}'. Available: {', '.join([f["id"] for f in fixtures])}"
        )

    # Resolve --input (with path/- support)
    if input is not None:
        sig = inspect.signature(pipeline_fn)
        params = [
            p
            for p in sig.parameters.values()
            if p.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        ]

        if input == "-":
            params_data = {}
            for param in params:
                params_data[param.name] = Prompt.ask(f"[blue]Enter[/] {param.name}")
            return Fixture(
                id="User_Input", context=params_data, description="Prompt Input"
            )
        else:
            if input.startswith("file://"):
                # Read from file
                path = Path(input.split("file://")[1])
                if not path.exists():
                    raise InputResolutionError(f"File not found: {input}")
                input = path.read_text()

            if _should_parse_as_structured(input):
                try:
                    parsed = _parse_structured_input(input)
                    LOGGER.info("Interpreting input as structured (JSON/YAML object)")
                    return Fixture(
                        id="User_Input", context=parsed, description="JSON/YAML Input"
                    )
                except InputResolutionError as e:
                    # Fall through to raw string handling
                    LOGGER.debug(
                        f"Failed to parse as structured: {e}. Going to Process as raw input."
                    )

            # Raw scalar input
            if len(params) == 1:
                # Single-parameter skill - bind raw string directly
                param_name = params[0].name
                LOGGER.info(f"Binding raw string to single parameter '{param_name}'")
                return Fixture(
                    id="User_Input",
                    context={param_name: input},
                    description="Raw Input",
                )
            else:
                # Multi-parameter skill - cannot infer mapping
                param_names = [p.name for p in params]
                raise InputResolutionError(
                    f"Skill '{pipeline_fn.__name__}' takes multiple parameters ({', '.join(param_names)}). "
                    f"Pass structured JSON/YAML input or use --arg flags (not yet implemented)."
                )

    # Should never reach here due to earlier checks
    raise InputResolutionError("No input source resolved (internal error)")
