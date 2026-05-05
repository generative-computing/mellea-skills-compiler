"""ClawDefender pipeline — P2 orchestration: intent classification + deterministic tool dispatch.

Session 1 (auto mode only): LLM classifies which security check to run based on input context.
Deterministic: invoke the appropriate ClawDefender bash tool.
Session 2 (auto mode only): LLM formats raw bash output into structured SecurityScanResult.
For explicit check_mode values, output is parsed deterministically without an LLM session.
"""

import json
import re

from mellea import start_session
from mellea.backends.model_options import ModelOption
from mellea.stdlib.sampling import RepairTemplateStrategy

from .config import (
    BACKEND,
    LOOP_BUDGET,
    MODEL_ID,
    PREFIX_TEXT,
    SCORE_CRITICAL,
    SCORE_HIGH,
    SCORE_WARNING,
)
from .schemas import ScanIntent, SecurityScanResult, SeverityLevel, ThreatFinding
from .tools import (
    _validate_command_injection,
    _validate_credential_exfil,
    _validate_path_traversal,
    _validate_prompt_injection,
    check_prompt,
    check_url,
    full_audit,
    safe_install,
    sanitize_external_input,
    scan_skill_files,
    validate_text,
)


def _parse_instruct_result(thunk, model_class):
    return model_class.model_validate_json(thunk.value)


def _safe_parse_with_fallback(thunk, model_class, **fallback_kwargs):
    try:
        return model_class.model_validate_json(thunk.value)
    except Exception:
        return model_class(**fallback_kwargs)


def _parse_raw_output(raw: str) -> SecurityScanResult:
    """Parse bash scan output into a SecurityScanResult deterministically."""
    # Try JSON format first (produced by some script modes)
    try:
        data = json.loads(raw.strip())
        sev_str = data.get("severity", "clean").lower()
        sev = SeverityLevel(sev_str) if sev_str in ("clean", "warning", "high", "critical") else SeverityLevel.CLEAN
        return SecurityScanResult(
            clean=bool(data.get("clean", True)),
            severity=sev,
            score=int(data.get("score", 0)),
            action=data.get("action", "allow"),
            findings=[],
            raw_output=raw,
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    upper = raw.upper()
    if "CRITICAL" in upper:
        score = SCORE_CRITICAL
        severity = SeverityLevel.CRITICAL
        action = "block"
        clean = False
    elif "HIGH" in upper:
        score = SCORE_HIGH
        severity = SeverityLevel.HIGH
        action = "block"
        clean = False
    elif "WARNING" in upper or "FLAGGED" in upper:
        score = SCORE_WARNING
        severity = SeverityLevel.WARNING
        action = "warn"
        clean = False
    else:
        score = 0
        severity = SeverityLevel.CLEAN
        action = "allow"
        clean = True

    findings: list[ThreatFinding] = []
    pattern = re.compile(r"(CRITICAL|HIGH|WARNING)\s*(?:\[([^\]]+)\])?", re.IGNORECASE)
    for match in pattern.finditer(raw):
        sev_str = match.group(1).lower()
        module = match.group(2) or "unknown"
        try:
            finding_sev = SeverityLevel(sev_str)
        except ValueError:
            finding_sev = SeverityLevel.WARNING
        finding_score = (
            SCORE_CRITICAL if finding_sev == SeverityLevel.CRITICAL
            else SCORE_HIGH if finding_sev == SeverityLevel.HIGH
            else SCORE_WARNING
        )
        findings.append(ThreatFinding(
            module=module,
            pattern=match.group(0),
            severity=finding_sev,
            score=finding_score,
        ))

    return SecurityScanResult(
        clean=clean,
        severity=severity,
        score=score,
        action=action,
        findings=findings,
        raw_output=raw,
    )


def _dispatch_tool(mode: str, target: str) -> str:
    """Deterministically invoke the correct ClawDefender tool for the given mode."""
    dispatch: dict[str, object] = {
        "audit": lambda: full_audit(),
        "sanitize": lambda: sanitize_external_input(target),
        "check_url": lambda: check_url(target),
        "check_prompt": lambda: check_prompt(target),
        "install": lambda: safe_install(target),
        "validate": lambda: validate_text(target),
        "scan_skill": lambda: scan_skill_files(target),
    }
    fn = dispatch.get(mode)
    if fn is None:
        return validate_text(target)
    return fn()  # type: ignore[operator]


def _run_validation_scan(input_text: str) -> SecurityScanResult:
    """Python-native multi-category scan orchestrating all _validate_* helpers.

    Combines prompt injection, command injection, credential exfiltration, and
    path traversal findings into a single SecurityScanResult without invoking
    the bash scripts. Used as a deterministic validation path.
    """
    all_findings = (
        _validate_prompt_injection(input_text)
        + _validate_command_injection(input_text)
        + _validate_credential_exfil(input_text)
        + _validate_path_traversal(input_text)
    )
    if not all_findings:
        return SecurityScanResult(
            clean=True,
            severity=SeverityLevel.CLEAN,
            score=0,
            action="allow",
            findings=[],
            raw_output="",
        )
    top = max(all_findings, key=lambda f: f.score)
    action = "block" if top.score >= SCORE_HIGH else "warn"
    return SecurityScanResult(
        clean=False,
        severity=top.severity,
        score=top.score,
        action=action,
        findings=all_findings,
        raw_output="",
    )


def run_pipeline(input_text: str, check_mode: str = "validate") -> SecurityScanResult:
    """Run a ClawDefender security scan and return a structured result.

    For explicit check_mode values the pipeline runs deterministically: invoke the
    appropriate bash tool and parse its output without any LLM calls.

    For check_mode="auto" the pipeline uses two LLM sessions (schema priming
    compliance): Session 1 classifies the intent; Session 2 formats the raw
    scan output into SecurityScanResult.

    Args:
        input_text: Text, URL, skill name, or directory path to scan.
                    Pass an empty string for workspace-wide audit mode.
        check_mode: Scan operation — one of:
                    "validate"    full multi-category text check (default),
                    "check_url"   SSRF / exfiltration URL check,
                    "check_prompt" prompt injection stdin check,
                    "sanitize"    sanitize external input with flagging,
                    "audit"       workspace-wide skill and script audit,
                    "scan_skill"  recursive directory scan,
                    "install"     safe skill installation + scan,
                    "auto"        LLM-classified intent dispatch.

    Returns:
        SecurityScanResult with threat findings and recommended action.
    """
    # ── Phase 1: intent classification (auto mode only) ───────────────────
    if check_mode == "auto":
        with start_session(BACKEND, MODEL_ID) as m:
            intent_thunk = m.instruct(
                "Classify what type of ClawDefender security check should be performed "
                "on the provided input. Consider: URLs → check_url, plain text that may "
                "contain injection → check_prompt or validate, skill directory paths → "
                "scan_skill, skill names for installation → install, empty or 'workspace' "
                "input → audit.",
                grounding_context={"input_text": str(input_text)},
                format=ScanIntent,
                model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            )
            intent = _safe_parse_with_fallback(
                intent_thunk,
                ScanIntent,
                query_type="validate",
                target=input_text,
                confidence=0.5,
            )
        resolved_mode = intent.query_type
        resolved_target = intent.target or input_text
    else:
        resolved_mode = check_mode
        resolved_target = input_text

    # ── Scope check ───────────────────────────────────────────────────────
    if resolved_mode == "out_of_scope":
        return SecurityScanResult(
            clean=True,
            severity=SeverityLevel.CLEAN,
            score=0,
            action="allow",
            findings=[],
            raw_output="",
        )

    # ── Phase 2: deterministic tool dispatch ─────────────────────────────
    raw_output = _dispatch_tool(resolved_mode, resolved_target)

    # ── Phase 3: structured output ────────────────────────────────────────
    if check_mode != "auto":
        # Explicit mode — deterministic parse, no LLM needed
        return _parse_raw_output(raw_output)

    # Auto mode — use LLM to produce a validated SecurityScanResult
    # (second start_session call — schema priming isolation from Session 1)
    with start_session(BACKEND, MODEL_ID) as m:
        result_thunk = m.instruct(
            "Parse the ClawDefender scan output below and produce a structured "
            "SecurityScanResult. Set clean=true only if no threats were found. "
            "Map CRITICAL findings to action=block, WARNING to action=warn, clean to action=allow.",
            grounding_context={
                "raw_output": str(raw_output),
                "check_mode": str(resolved_mode),
            },
            format=SecurityScanResult,
            model_options={ModelOption.SYSTEM_PROMPT: PREFIX_TEXT},
            strategy=RepairTemplateStrategy(loop_budget=LOOP_BUDGET),
        )
        parsed = _safe_parse_with_fallback(
            result_thunk,
            SecurityScanResult,
            clean=True,
            severity=SeverityLevel.CLEAN,
            score=0,
            action="allow",
            findings=[],
            raw_output=raw_output,
        )

    # Ensure raw_output is populated even if the LLM omitted it
    if not parsed.raw_output:
        parsed = parsed.model_copy(update={"raw_output": raw_output})
    return parsed
