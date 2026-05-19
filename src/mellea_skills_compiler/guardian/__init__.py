"""Runtime governance hooks for Mellea pipelines."""

from pathlib import Path
from typing import Optional

from mellea.plugins import register, unregister

from mellea_skills_compiler.certification.nexus_policy import PolicyManifest
from mellea_skills_compiler.enums import InferenceEngineType
from mellea_skills_compiler.guardian.audit_trail import AuditTrailPlugin
from mellea_skills_compiler.guardian.guardian_hook import GuardianAuditPlugin
from mellea_skills_compiler.toolkit.logging import configure_logger

LOGGER = configure_logger()


def register_plugins(
    manifest: PolicyManifest,
    log_dir: Path = None,
    enforce: bool = False,
    guardian_model: Optional[str] = None,
    inference_engine: InferenceEngineType = InferenceEngineType.OLLAMA,
) -> tuple:
    guardian = GuardianAuditPlugin.from_manifest(
        manifest,
        enforce=enforce,
        guardian_model=guardian_model,
        inference_engine=inference_engine,
    )

    # Clear audit log
    AUDIT_LOG = (
        log_dir / "runtime_audit.jsonl" if log_dir else "runtime_audit.jsonl"
    )
    if AUDIT_LOG.exists():
        AUDIT_LOG.unlink()

    audit = AuditTrailPlugin(
        log_path=AUDIT_LOG,
        policy_id=f"nexus-{manifest.taxonomy}",
        guardian_ref=guardian,
    )

    register(guardian)
    register(audit)

    LOGGER.info(
        f"Guardian registered: {len(manifest.risks)} risks, mode={'enforce' if enforce else 'audit'}",
    )
    LOGGER.info("Audit trail: %s", AUDIT_LOG)

    return guardian, audit


def deregister_plugins(*plugins) -> None:
    """Remove Guardian and Audit plugins from the global registry."""
    try:
        for plugin in plugins:
            if plugin is not None:
                unregister(plugin)
    except (ImportError, Exception):
        pass
