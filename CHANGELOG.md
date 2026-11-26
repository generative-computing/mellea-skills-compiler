# Changelog

## Unreleased

### Breaking: mellea 0.9 is now required

The compiler now pins `mellea[hooks]>=0.9.0,<0.10` (previously `>=0.7.0,<0.8`).

- **Environment sharing:** skills compiled with the previous pin
  (`mellea>=0.7.0,<0.8`) can no longer share a Python environment with this
  compiler. Recompile them, or keep them in a separate environment on mellea 0.7.
- **Why 0.9.0 is the lower bound:** 0.8 removed or renamed APIs (streaming
  `stream()`, `render_controls`, `set_request_adapter`; `json_util` became
  private), and 0.9 changed behaviour (async `Requirement.validate` is now
  awaited; empty user content is rejected). The test suite and hook-payload
  probes are validated on 0.9.0, so earlier releases are unsupported.
- **Docs:** `mellea-fy-behaviours` bumped to 4.5.0 (tested against mellea 0.9.x).
