from enum import Enum, StrEnum, auto


class ClaudeResponseType(StrEnum):
    ASSISTANT = auto()
    SYSTEM = auto()


class ClaudeResponseMessageType(StrEnum):
    TEXT = auto()


class InferenceEngineType(Enum):
    """Enum to contain possible values for inference engine types"""

    OLLAMA = auto()

    @classmethod
    def list(cls):
        return list(map(lambda c: c.name, cls))

    def __str__(self):
        return self.name


class InferenceModel(StrEnum):
    """Default model identifiers"""

    OLLAMA_RISK_MODEL = "granite3.3:8b"
    OLLAMA_GUARDIAN_MODEL = "ibm/granite3.3-guardian:8b"
    CLAUDE_MODEL = "sonnet"


class SpecFileFormat(StrEnum):
    """Default spec file identifiers"""

    SKILL_FILE_MD = "SKILL.md"
    SPEC_FILE_MD = "spec.md"


class GovernanceTaxonomy(StrEnum):
    """Default taxonomy identifiers"""

    IBM_GRANITE_GUARDIAN = "ibm-granite-guardian"
    NIST_AI_RMF = "nist-ai-rmf"
    CREDO_UCF = "credo-ucf"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class CoverageLevel(Enum):
    AUTOMATED = "AUTOMATED"
    PARTIAL = "PARTIAL"
    MANUAL = "MANUAL"


class GuardianMode(StrEnum):
    DISABLED = "disabled"
    ENFORCE = "enforce"
    AUDIT = "audit"

    def __str__(self):
        return self.name


class NexusRiskSource(StrEnum):
    DEFAULT_FALLBACK = "default-fallback"
    AI_ATLAS_NEXUS = "ai-atlas-nexus"


class GuardianScore(StrEnum):
    YES = "Yes"
    NO = "No"
    FAILED = "Failed"
    ERROR = "Error"
