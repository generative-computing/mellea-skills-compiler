from enum import Enum, StrEnum, auto
from typing import List, Literal


class ClaudeMessageType(StrEnum):
    ASSISTANT = auto()
    SYSTEM = auto()
    TEXT = auto()


class BOBMessageType(StrEnum):
    MESSAGE = auto()
    TOOL_USE = auto()
    ERROR = auto()
    RESULT = auto()


class PiMessageType(StrEnum):
    SESSION = auto()
    AGENT_START = auto()
    TURN_START = auto()
    MESSAGE_START = auto()
    MESSAGE_UPDATE = auto()
    MESSAGE_END = auto()
    TURN_END = auto()
    AGENT_END = auto()
    AGENT_SETTLED = auto()


class InferenceEngineType(Enum):
    """Enum to contain possible values for inference engine types"""

    OLLAMA = auto()
    VLLM = auto()

    @classmethod
    def list(cls) -> List[str]:
        return list(map(lambda c: c.name, cls))

    def __str__(self) -> Literal["OLLAMA", "VLLM"]:
        return self.name


class InferenceModelType(Enum):
    """Default model types"""

    RISK_MODEL = auto()
    GUARDIAN_MODEL = auto()


class InferenceModel(StrEnum):
    """Default model identifiers"""

    OLLAMA_RISK_MODEL = "granite4.1:3b"
    OLLAMA_GUARDIAN_MODEL = "ibm/granite3.3-guardian:8b"
    VLLM_RISK_MODEL = "ibm-granite/granite-4.1-3b"
    VLLM_GUARDIAN_MODEL = "ibm-granite/granite-guardian-3.3-8b"
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
    OWASP_ASI = "owasp-asi"

    @classmethod
    def list(cls) -> List[str]:
        return list(map(lambda c: c.value, cls))


class CoverageLevel(Enum):
    AUTOMATED = "AUTOMATED"
    PARTIAL = "PARTIAL"
    MANUAL = "MANUAL"


class GuardianMode(StrEnum):
    DISABLED = "disabled"
    ENFORCE = "enforce"
    AUDIT = "audit"

    def __str__(self) -> Literal["DISABLED", "ENFORCE", "AUDIT"]:
        return self.name


class NexusRiskSource(StrEnum):
    DEFAULT_FALLBACK = "default-fallback"
    AI_ATLAS_NEXUS = "ai-atlas-nexus"


class GuardianScore(StrEnum):
    YES = "Yes"
    NO = "No"
    FAILED = "Failed"
    ERROR = "Error"


class HookStage(StrEnum):

    PRE = "pre"
    POST = "post"
    TOOLS_PRE = "tools_pre"
    TOOLS_POST = "tools_post"

    @classmethod
    def list(cls) -> List[str]:
        return list(map(lambda c: c.value, cls))
