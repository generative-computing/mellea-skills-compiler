"""Backend abstraction layer for mellea-skills compilation.

This module defines the protocol that all compilation backends must implement,
enabling support for multiple compilation engines (Claude Code, IBM Bob, local LLMs, etc.)
while maintaining a consistent interface.

The abstraction layer consists of:
- CompilationBackend: Protocol defining the contract for compilation backends
- CompilationContext: Input parameters for compilation
- CompilationResult: Output from compilation process
- BackendRegistry: Registry for managing available backends

Example usage:
    >>> from mellea_skills_compiler.compile.backend import get_backend, CompilationContext
    >>> backend = get_backend("claude")
    >>> context = CompilationContext(
    ...     spec_path=Path("skill/spec.md"),
    ...     package_dir=Path("output/skill_mellea"),
    ...     intermediate_dir=Path("output/skill_mellea/intermediate"),
    ... )
    >>> result = backend.compile(context)
    >>> if result.success:
    ...     print(f"Compiled to {result.package_dir}")
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Protocol, Type


@dataclass
class CompilationContext:
    """Input context for compilation process.

    This dataclass encapsulates all parameters needed to execute a compilation,
    providing a clean interface between the CLI/API layer and backend implementations.

    Attributes:
        spec_path: Path to the input specification file (spec.md or SKILL.md)
        package_dir: Directory where the compiled Mellea package will be written
        intermediate_dir: Directory for intermediate artifacts (JSON, logs, etc.)
        model: Optional model identifier for the compilation backend (e.g., "claude-3-7-sonnet-20250219")
        timeout: Maximum time in seconds for compilation (0 = no timeout)
        repair_mode: If True, use repair workflow instead of full compilation
        skill_backend: Runtime backend for the compiled skill (e.g., "claude", "bob")
        skill_model: Runtime model for the compiled skill
        defaults_source: Source of where the backend values came from (e.g. "command-line", "file")
        refresh_cache: If True, force refresh of cached artifacts
        provider: Optional provider identifier for the compilation backend
            (pi-only; e.g. "anthropic", "ollama"). Ignored by backends that
            don't support provider selection.

    Example:
        >>> context = CompilationContext(
        ...     spec_path=Path("weather/spec.md"),
        ...     package_dir=Path("weather_mellea"),
        ...     intermediate_dir=Path("weather_mellea/intermediate"),
        ...     model="claude-3-7-sonnet-20250219",
        ...     timeout=300,
        ... )
    """

    spec_path: Path
    package_dir: Path
    intermediate_dir: Path
    model: Optional[str] = None
    timeout: int = 0
    repair_mode: bool = False
    skill_backend: Optional[str] = None
    skill_model: Optional[str] = None
    defaults_source: Optional[str] = None
    refresh_cache: bool = False
    provider: Optional[str] = None


@dataclass
class CompilationResult:
    """Result of a compilation process.

    This dataclass encapsulates the outcome of a compilation attempt, including
    success status, output locations, error information, and backend-specific metadata.

    Attributes:
        success: True if compilation completed successfully, False otherwise
        package_dir: Path to the compiled Mellea package directory
        error_message: Human-readable error description if success=False, None otherwise
        intermediate_artifacts: Mapping of artifact names to their file paths
            (e.g., {"inventory": Path("intermediate/inventory.json")})
        metadata: Backend-specific metadata (e.g., model used, tokens consumed, timing info)

    Example:
        >>> result = CompilationResult(
        ...     success=True,
        ...     package_dir=Path("weather_mellea"),
        ...     intermediate_artifacts={
        ...         "inventory": Path("weather_mellea/intermediate/inventory.json"),
        ...         "classification": Path("weather_mellea/intermediate/classification.json"),
        ...     },
        ...     metadata={"model": "claude-3-7-sonnet-20250219", "duration_seconds": 45.2},
        ... )
    """

    success: bool
    package_dir: Path
    error_message: Optional[str] = None
    intermediate_artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CompilationBackend(Protocol):
    """Protocol defining the interface for compilation backends.

    All compilation backends (Claude Code, IBM Bob, local LLMs, etc.) must implement
    this protocol to be compatible with the mellea-skills-compiler framework.

    The protocol defines four core methods that backends must provide:
    1. identifier() - Return identifier for usage across APIs
    2. name() - Return human-readable backend name for logging purpose
    3. compile() - Execute the full compilation workflow
    4. validate_environment() - Check if backend prerequisites are met
    5. supports_repair_mode() - Indicate repair mode capability

    Backends are responsible for:
    - Decomposing skill specifications into Mellea pipeline components
    - Generating all required artifacts (config.py, schemas.py, tools.py, etc.)
    - Handling errors and timeouts gracefully
    - Providing clear error messages for debugging

    Example implementation:
        >>> class MyBackend:
        ...     def compile(self, context: CompilationContext) -> CompilationResult:
        ...         # Implementation here
        ...         return CompilationResult(success=True, package_dir=context.package_dir)
        ...
        ...     def validate_environment(self) -> tuple[bool, Optional[str]]:
        ...         return True, None
        ...
        ...     def get_backend_name(self) -> str:
        ...         return "My Custom Backend"
        ...
        ...     def supports_repair_mode(self) -> bool:
        ...         return False
    """

    @staticmethod
    def identifier() -> str:
        """Return internal identifer for the given compiler

        Returns:
            A short compiler identifer e.g. bob, claude
        """
        ...

    def name(self) -> str:
        """Return human-readable backend name for logging and display.

        This name is used in:
        - Log messages ("Using compilation backend: Claude Code")
        - Error messages ("Backend 'Claude Code' failed: ...")
        - CLI help text ("Available backends: claude, bob")

        Returns:
            A short, descriptive name (e.g., "Claude Code", "IBM Bob", "Local Llama")

        Example:
            >>> backend = get_backend("claude")
            >>> print(backend.get_backend_name())
            Claude Code
        """
        ...

    def compile(self, context: CompilationContext) -> CompilationResult:
        """Execute the full compilation workflow.

        This method orchestrates the 10-step compilation process:
        1. Parse specification and extract metadata
        2. Generate inventory of required components
        3. Classify skill type and complexity
        4. Map specification elements to Mellea primitives
        5. Generate dependency plan
        6. Emit configuration (config.py)
        7. Emit schemas (schemas.py)
        8. Emit tools (tools.py)
        9. Emit pipeline (pipeline.py)
        10. Emit fixtures for testing

        Args:
            context: Compilation parameters including paths, model, timeout, etc.

        Returns:
            CompilationResult with success status, output paths, and metadata

        Raises:
            RuntimeError: If compilation fails due to backend-specific errors
            TimeoutError: If compilation exceeds context.timeout (if timeout > 0)

        Example:
            >>> backend = get_backend("claude")
            >>> context = CompilationContext(
            ...     spec_path=Path("weather/spec.md"),
            ...     package_dir=Path("weather_mellea"),
            ...     intermediate_dir=Path("weather_mellea/intermediate"),
            ... )
            >>> result = backend.compile(context)
            >>> if result.success:
            ...     print(f"Success! Package at {result.package_dir}")
            ... else:
            ...     print(f"Failed: {result.error_message}")
        """
        ...

    def validate_environment(self) -> tuple[bool, Optional[str]]:
        """Check if backend prerequisites are met.

        This method verifies that the backend can execute successfully by checking:
        - Required CLI tools are installed and accessible
        - API credentials are configured (if needed)
        - Network connectivity (if needed)
        - Any other backend-specific requirements

        This should be called before attempting compilation to provide early,
        actionable error messages to users.

        Returns:
            A tuple of (is_valid, error_message) where:
            - is_valid: True if all prerequisites are met, False otherwise
            - error_message: None if valid, or a helpful error message explaining
              what's missing and how to fix it

        Example:
            >>> backend = get_backend("claude")
            >>> is_valid, error = backend.validate_environment()
            >>> if not is_valid:
            ...     print(f"Backend not ready: {error}")
            ...     print("Please install Claude Code: https://docs.anthropic.com/...")
        """
        ...

    def supports_repair_mode(self) -> bool:
        """Indicate whether this backend supports repair mode.

        Repair mode is a specialized workflow that attempts to fix compilation
        errors by analyzing failed artifacts and regenerating specific components.
        Not all backends may support this advanced feature.

        Returns:
            True if backend implements repair mode, False otherwise

        Example:
            >>> backend = get_backend("claude")
            >>> if backend.supports_repair_mode():
            ...     context.repair_mode = True
            ... else:
            ...     print("Repair mode not available for this backend")
        """
        ...


class BackendRegistry:
    """Registry for managing available compilation backends.

    This class provides a centralized registry for backend implementations,
    allowing dynamic registration and retrieval of backends by name.

    Backends are registered with a string identifier (e.g., "claude", "bob")
    and can be retrieved by that identifier. The registry ensures that:
    - Backend names are unique (no duplicate registrations)
    - Unknown backends raise clear errors
    - Available backends can be listed for CLI help text

    Example:
        >>> from mellea_skills_compiler.compile.backend import BackendRegistry
        >>> from mellea_skills_compiler.compile.backends.claude import ClaudeCodeBackend
        >>>
        >>> registry = BackendRegistry()
        >>> registry.register_backend("claude", ClaudeCodeBackend)
        >>>
        >>> backend = registry.get_backend("claude")
        >>> print(backend.get_backend_name())
        Claude Code
        >>>
        >>> print(registry.list_backends())
        ['claude']
    """

    def __init__(self) -> None:
        """Initialize an empty backend registry."""
        self._backends: dict[str, Type[CompilationBackend]] = {}

    def register_backend(self, backend_class: Type[CompilationBackend]) -> None:
        """Register a backend implementation.

        Args:
            backend_class: Class implementing the CompilationBackend protocol

        Raises:
            ValueError: If a backend with this name is already registered

        Example:
            >>> registry = BackendRegistry()
            >>> registry.register_backend(ClaudeCodeBackend)
            >>> registry.register_backend(BobBackend)
        """
        if backend_class.identifier() in self._backends:
            raise ValueError(
                f"Backend '{backend_class.identifier()}' is already registered"
            )
        self._backends[backend_class.identifier()] = backend_class

    def get_backend(self, identifier: str) -> CompilationBackend:
        """Retrieve a backend by identifier.

        Args:
            identifier: Backend identifier (e.g., "claude", "bob")

        Returns:
            An instance of the requested backend

        Raises:
            ValueError: If no backend with this identifier is registered

        Example:
            >>> registry = BackendRegistry()
            >>> registry.register_backend(ClaudeCodeBackend)
            >>> backend = registry.get_backend("claude")
            >>> print(backend.name())
            Claude Code
        """
        if identifier not in self._backends:
            available = ", ".join(self.list_backends())
            raise ValueError(
                f"Unknown compilation backend - '{identifier}'. Available backends: [{available}]"
            )
        return self._backends[identifier]()

    def list_backends(self) -> List[str]:
        """List all registered backend identifiers.

        Returns:
            Sorted list of backend identifiers

        Example:
            >>> registry = BackendRegistry()
            >>> registry.register_backend("claude", ClaudeCodeBackend)
            >>> registry.register_backend("bob", BobBackend)
            >>> print(registry.list_backends())
            ['bob', 'claude']
        """
        return sorted(self._backends.keys())


# Global registry instance
global_registry: BackendRegistry = BackendRegistry()
