"""ClawDefender tool implementations — thin Python wrappers around bundled bash scripts.

All script paths are resolved package-relatively via Path(__file__).parent so the
package works correctly whether installed via pip or invoked directly.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from .config import SCORE_CRITICAL, SCORE_HIGH, SCORE_WARNING
from .schemas import SeverityLevel, ThreatFinding


# === C2: Operating Rules — Detection Pattern Constants ===
# These mirror the arrays in scripts/clawdefender.sh for reference.
# Actual pattern matching is performed by the bundled bash scripts.
# PROVENANCE: scripts/clawdefender.sh:41-107 + SKILL.md:131-148

PROMPT_INJECTION_CRITICAL: Final[tuple[str, ...]] = (
    "show.*your.*api.?key",
    "send.*api.?key",
    "read.*config.*key",
    "what.*your.*api.?key",
    "tell me.*password",
    "show.*password",
    "read.*[.]env",
    "contents of.*[.]env",
    "show.*secret",
    "send.*credentials",
    "what.*credentials",
    "dump.*credential",
    "paste.*[.]env",
    "[.]env.*content",
    "what.*openclaw",
    "what.*.openclaw",
    "what.*.clawdbot",
    "what.*clawdbot",
    "show.*clawdbot",
    "send.*clawdbot",
    "read.*clawdbot",
    "read.*.clawdbot",
    "show.*openclaw",
    "read.*openclaw",
    "read.*.openclaw",
    "list.*credentials",
    "dump.*credentials",
    "send.*[.]env",
    "paste.*[.]env",
    "contents.*[.]env",
    "show.*[.]env",
    "what.*in.*config",
    "ignore previous instructions",
    "ignore all previous",
    "ignore your instructions",
    "disregard above",
    "disregard.*instructions",
    "disregard.*prompt",
    "disregard previous",
    "forget.*instructions",
    "forget everything",
    "forget your instructions",
    "forget everything above",
    "override your instructions",
    "new system prompt",
    "reset to default",
    "new instructions",
    "you are no longer",
    "disable.*safety",
    "disable.*filter",
    "no restrictions",
    "without.*restrictions",
    "remove.*restrictions",
    "without.*guidelines",
    "no.*ethical",
    "reveal.*system prompt",
    "show.*system prompt",
    "print.*system prompt",
    "what.*instructions.*given",
    "what.*your instructions",
    "print.*conversation",
    "show.*conversation history",
    "export.*history",
    "export all.*data",
    "export.*user.*data",
)
# PROVENANCE: scripts/clawdefender.sh:41-107

PROMPT_INJECTION_WARNING: Final[tuple[str, ...]] = (
    "you are now",
    "your new role",
    "pretend to be",
    "act as if",
    "roleplay as",
    "hypothetically",
    "for educational purposes",
    "SYSTEM:",
    r"\[INST\]",
    "<<SYS>>",
    "jailbreak",
    "DAN mode",
    "pretend.*DAN",
    "you're DAN",
    "for academic",
    "in a fictional",
    "in a hypothetical",
    "imagine a world",
    "translate.*then execute",
    "translate.*then run",
    "base64.*decode",
    "rot13",
    "developer mode",
    "---END",
    "END OF SYSTEM",
    "END OF PROMPT",
    "<|endoftext|>",
    "###.*SYSTEM",
    "BEGIN NEW INSTRUCTIONS",
    "STOP IGNORE",
)
# PROVENANCE: scripts/clawdefender.sh:109-141

COMMAND_INJECTION: Final[tuple[str, ...]] = (
    "rm -rf /",
    r"rm -rf \*",
    "chmod 777",
    r"mkfs\.",
    "dd if=/dev",
    r":\(\)\{ :\|:& \};:",
    "nc -e",
    "ncat -e",
    "bash -i >& /dev/tcp",
    "/dev/tcp/",
    "/dev/udp/",
    r"\| bash",
    r"\| sh",
    r"curl.*\| bash",
    r"wget.*\| sh",
    r"base64 -d \| bash",
    r"base64 --decode \| sh",
    r"eval.*\$\(",
    "python -c.*exec",
)
# PROVENANCE: scripts/clawdefender.sh:143-164

CREDENTIAL_EXFIL: Final[tuple[str, ...]] = (
    r"webhook\.site",
    r"requestbin\.com",
    r"requestbin\.net",
    r"pipedream\.net",
    r"hookbin\.com",
    r"beeceptor\.com",
    r"ngrok\.io",
    r"curl.*-d.*[.]env",
    r"curl.*--data.*[.]env",
    r"cat.*[.]env.*curl",
    "POST.*webhook.site.*API_KEY",
    "POST.*webhook.site.*SECRET",
    "POST.*webhook.site.*TOKEN",
)
# PROVENANCE: scripts/clawdefender.sh:166-181

SSRF_PATTERNS: Final[tuple[str, ...]] = (
    "localhost",
    r"127\.0\.0\.1",
    r"0\.0\.0\.0",
    r"10\.\d+\.\d+\.\d+",
    r"172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+",
    r"192\.168\.\d+\.\d+",
    r"169\.254\.169\.254",
    "metadata.google",
    r"\[::1\]",
)
# PROVENANCE: scripts/clawdefender.sh:183-194

PATH_TRAVERSAL: Final[tuple[str, ...]] = (
    ".config/openclaw",
    ".openclaw",
    "the .openclaw",
    ".openclaw directory",
    ".openclaw folder",
    "openclaw.json",
    ".config/gog",
    r"cat.*[.]env",
    r"read.*[.]env",
    r"show.*[.]env",
    "/.env",
    "config.yaml",
    "config.json",
    ".ssh/id_",
    ".gnupg",
    r"\.\./\.\./\.\.",
    "/etc/passwd",
    "/etc/shadow",
    "/root/",
    "~/.ssh/",
    "~/.aws/",
    "~/.gnupg/",
    "%2e%2e%2f",
    r"\.\.%2f",
    "%2e%2e/",
)
# PROVENANCE: scripts/clawdefender.sh:196-223

SENSITIVE_FILES: Final[tuple[str, ...]] = (
    "[.]env",
    "id_rsa",
    r"\.pem",
    "secret",
    "password",
    "api.key",
    "token",
)
# PROVENANCE: scripts/clawdefender.sh:225-234

ALLOWED_DOMAINS: Final[tuple[str, ...]] = (
    "github.com",
    "api.github.com",
    "api.openai.com",
    "api.anthropic.com",
    "googleapis.com",
    "google.com",
    "npmjs.org",
    "pypi.org",
    "wttr.in",
    "signalwire.com",
    "usetrmnl.com",
)
# PROVENANCE: scripts/clawdefender.sh:236-249

def log_finding(severity: str, module: str, message: str, score: int) -> None:
    """Record a security finding to stderr for diagnostic visibility."""
    print(f"[{severity.upper()}] [{module}] {message} (score={score})", file=sys.stderr)


def check_patterns(
    input_text: str,
    patterns: tuple[str, ...],
    module: str,
    base_score: int,
) -> list[ThreatFinding]:
    """Scan input_text against each regex pattern; return matching ThreatFindings."""
    sev = (
        SeverityLevel.CRITICAL if base_score >= SCORE_CRITICAL
        else SeverityLevel.HIGH if base_score >= SCORE_HIGH
        else SeverityLevel.WARNING
    )
    findings: list[ThreatFinding] = []
    for pat in patterns:
        try:
            if re.search(pat, input_text, re.IGNORECASE):
                findings.append(ThreatFinding(
                    module=module,
                    pattern=pat,
                    severity=sev,
                    score=base_score,
                ))
        except re.error:
            pass
    return findings


def is_allowed_domain(url: str) -> bool:
    """Return True if the URL's hostname is in the ALLOWED_DOMAINS allowlist."""
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return False
    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in ALLOWED_DOMAINS
    )


def _validate_prompt_injection(input_text: str) -> list[ThreatFinding]:
    """Scan input_text for prompt injection patterns across critical and warning tiers."""
    findings = check_patterns(input_text, PROMPT_INJECTION_CRITICAL, "prompt_injection", SCORE_CRITICAL)
    findings += check_patterns(input_text, PROMPT_INJECTION_WARNING, "prompt_injection_warning", SCORE_WARNING)
    return findings


def _validate_command_injection(input_text: str) -> list[ThreatFinding]:
    """Scan input_text for shell command injection patterns."""
    return check_patterns(input_text, COMMAND_INJECTION, "command_injection", SCORE_CRITICAL)


def _validate_credential_exfil(input_text: str) -> list[ThreatFinding]:
    """Scan input_text for credential exfiltration patterns."""
    return check_patterns(input_text, CREDENTIAL_EXFIL, "credential_exfil", SCORE_CRITICAL)


def _validate_url(url: str) -> list[ThreatFinding]:
    """Scan a URL for SSRF and private-network access patterns."""
    return check_patterns(url, SSRF_PATTERNS, "ssrf", SCORE_CRITICAL)


def _validate_path_traversal(input_text: str) -> list[ThreatFinding]:
    """Scan input_text for path traversal and sensitive file access patterns."""
    return check_patterns(input_text, PATH_TRAVERSAL, "path_traversal", SCORE_HIGH)


_SCRIPT_TIMEOUT = 60


def _clawdefender_script() -> Path:
    return Path(__file__).parent / "scripts" / "clawdefender.sh"


def _sanitize_script() -> Path:
    return Path(__file__).parent / "scripts" / "sanitize.sh"


def _run_script(cmd: list[str], input_text: str | None = None) -> str:
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=_SCRIPT_TIMEOUT,
    )
    combined = result.stdout
    if result.stderr:
        combined = combined + result.stderr if combined else result.stderr
    return combined.strip()


def full_audit(workspace_dir: str = "") -> str:
    """Run a workspace-wide security audit scanning all skills, scripts, and .env permissions.

    Scans all installed skills and scripts for security issues.
    Output shows clean skills (✓) and flagged files with severity.

    Args:
        workspace_dir: Optional override for the workspace root path.
                       Defaults to the path configured in the bundled script.

    Returns:
        Human-readable audit report with per-file findings or ✓ Clean indicators.
    """
    script = _clawdefender_script()
    cmd = [str(script), "--audit"]
    if workspace_dir:
        cmd = ["env", f"WORKSPACE={workspace_dir}", str(script), "--audit"]
    return _run_script(cmd)


def sanitize_external_input(input_text: str, mode: str = "default") -> str:
    """Sanitize external input by checking for prompt injection patterns.

    Universal wrapper that checks any text for prompt injection.
    Flagged content is wrapped with ⚠️ [FLAGGED] markers.
    Clean content passes through unchanged.

    Args:
        input_text: The text to sanitize (reads from stdin in the script).
        mode: One of "default" (passthrough with warning markers),
              "json" (JSON-format output), "strict" (exit 1 on detection),
              "report" (findings only), "silent" (no warnings).

    Returns:
        Sanitized output — flagged content wrapped with markers, or raw output when clean.
    """
    script = _sanitize_script()
    mode_flags: dict[str, list[str]] = {
        "default": [],
        "json": ["--json"],
        "strict": ["--strict"],
        "report": ["--report"],
        "silent": ["--silent"],
    }
    flags = mode_flags.get(mode, [])
    cmd = [str(script)] + flags
    # sanitize.sh reads from stdin — pass input_text via input=, not as a positional arg
    return _run_script(cmd, input_text=input_text)


def check_url(url: str) -> str:
    """Validate a URL before fetching to prevent SSRF and data exfiltration.

    Checks the URL against the SSRF pattern list and domain allowlist.
    Safe URLs return "✅ URL appears safe"; blocked URLs describe the threat.

    Args:
        url: The URL to validate.

    Returns:
        Status message indicating whether the URL is safe or which threat was detected.
    """
    script = _clawdefender_script()
    return _run_script([str(script), "--check-url", url])


def check_prompt(text: str) -> str:
    """Check arbitrary text for prompt injection patterns.

    Validates text against all PROMPT_INJECTION_CRITICAL and PROMPT_INJECTION_WARNING
    patterns. Returns CRITICAL / WARNING / ✅ Clean status.

    Args:
        text: The text to check (reads from stdin in the script).

    Returns:
        Detection result: "🔴 CRITICAL: prompt injection detected", "🟡 WARNING: ...",
        or "✅ Clean".
    """
    script = _clawdefender_script()
    # clawdefender.sh --check-prompt reads from stdin
    return _run_script([str(script), "--check-prompt"], input_text=text)


def safe_install(skill_name: str) -> str:
    """Install a skill from ClawHub and scan it for security issues.

    Runs `npx clawhub install <skill_name>` then scans the installed skill.
    Warns if critical issues are found.

    Args:
        skill_name: The ClawHub skill slug to install.

    Returns:
        Installation and scan output, including any security warnings.
    """
    script = _clawdefender_script()
    return _run_script([str(script), "--install", skill_name])


def validate_text(text: str) -> str:
    """Check text against all threat pattern categories.

    Runs full multi-category detection: prompt injection, command injection,
    credential exfiltration, SSRF, and path traversal.

    Args:
        text: The text to validate (passed as a positional argument).

    Returns:
        Detection report with CRITICAL/HIGH/WARNING findings or "✅ Clean".
    """
    script = _clawdefender_script()
    return _run_script([str(script), "--validate", text])


def scan_skill_files(skill_dir: str) -> str:
    """Recursively scan a skill directory for security issues.

    Scans all .md, .sh, .js, .py, .ts files in the directory (excluding
    node_modules, .git, and .min.js files). Reports per-file findings or ✓ Clean.

    Args:
        skill_dir: Absolute or relative path to the skill directory to scan.

    Returns:
        Per-file scan report with findings or clean indicators.
    """
    script = _clawdefender_script()
    return _run_script([str(script), "--scan-skill", skill_dir])
