from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    CLEAN = "clean"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatFinding(BaseModel):
    module: str = Field(description="Detection module that found the threat (e.g. prompt_injection, command_injection)")
    pattern: str = Field(description="Pattern string that triggered the match")
    severity: SeverityLevel = Field(description="Severity level of this finding")
    score: int = Field(description="Numeric threat score (0–100)")


class SecurityScanResult(BaseModel):
    clean: bool = Field(description="True when no threats were detected")
    severity: SeverityLevel = Field(description="Highest severity level found across all findings")
    score: int = Field(description="Highest threat score found (0–100)")
    action: Literal["allow", "warn", "block"] = Field(description="Recommended action: allow / warn / block")
    findings: list[ThreatFinding] = Field(default_factory=list, description="Individual threat findings, empty when clean")
    raw_output: str = Field(default="", description="Raw text output from the underlying scan script")


class ScanIntent(BaseModel):
    """Intent classification result used by the P2 LLM intent step (auto mode only)."""
    query_type: Literal[
        "validate", "check_url", "check_prompt", "sanitize",
        "audit", "scan_skill", "install", "out_of_scope"
    ] = Field(description="Which scan operation to perform")
    target: str = Field(default="", description="Extracted target (URL, skill name, or full input text)")
    confidence: float = Field(default=0.8, description="Classification confidence 0.0–1.0")
