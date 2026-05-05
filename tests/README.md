# Mellea Skills Compiler Tests

This directory contains unit tests for the Mellea Skills Compiler package.

## Dependencies

Tests require:

- `pytest>=7.0` - Testing framework
- `pytest-cov` (optional) - Coverage reporting

Or install tests dependencies:

```bash
pip install -e ".[tests]"
```

## Running Tests

### Run all tests

```bash
pytest
```

### Run tests with coverage

```bash
pytest --cov=mellea_skills_compiler --cov-report=html
```

### Run specific test file

```bash
pytest tests/test_enums.py
```

### Run specific test class or function

```bash
pytest tests/mellea_skills_compiler/certification/test_compliance.py::TestComplianceSummary
pytest tests/mellea_skills_compiler/toolkit/test_file_utils.py::TestParseSkillMd::test_parse_with_valid_frontmatter
```

### Run with verbose output

```bash
pytest -v
```

### Run with output capture disabled (see print statements)

```bash
pytest -s
```

## Test Structure

- `tests/mellea_skills_compiler/toolkit/test_file_utils.py` - Tests for file parsing utilities
- `tests/mellea_skills_compiler/certification/test_nexus_policy.py` - Tests for policy manifest and Nexus integration
- `tests/mellea_skills_compiler/certification/test_compliance.py` - Tests for compliance classification and reporting
- `tests/mellea_skills_compiler/guardian/test_audit_trail.py` - Tests for audit trail plugin
