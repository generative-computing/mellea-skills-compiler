# From Stubs to Running — Filling the Gaps After Compile

When `mellea-skills compile` finishes, the post-compile smoke check
sometimes prints a warning, or — in skills that wrap their stub call
sites — runs to completion but reports "unverified" everywhere. Both
mean the same thing: the compiler emitted `NotImplementedError` stubs
for tools whose host implementation the spec did not pin down.

The worked example is `sentry-find-bugs`: two stubs (`search_fn`,
`read_file_fn`), each implementable in five lines of standard library.

---

## 1. The T1 Demo First — No Stubs Required

Before touching any stub, confirm the package is functional:

```bash
mellea-skills run src/mellea_skills_compiler/examples/sentry-find-bugs/sentry_find_bugs_mellea \
  --fixture clean_secure_parameterized
```

This fixture's diff is large enough (over 500 chars) and clean enough
that neither stub is invoked: the diff-augmentation branch is gated on
`len(diff) < 500`, and Phase 4 produces no candidate issues. See
[`README.md`](README.md) §3 for the captured output.

---

## 2. Find Every Stub

```bash
grep -n "raise NotImplementedError" \
  src/mellea_skills_compiler/examples/sentry-find-bugs/sentry_find_bugs_mellea/constrained_slots.py
```

Expected output:

```
21:    raise NotImplementedError(
39:    raise NotImplementedError(
```

Two stubs, matching the count in `SETUP.md §8`:

| Name           | Lines | Signature                                                             |
| -------------- | ----- | --------------------------------------------------------------------- |
| `search_fn`    | 6–24  | `search_fn(pattern: str) -> list[str]`                                |
| `read_file_fn` | 27–42 | `read_file_fn(file_path: str, start_line: int, end_line: int) -> str` |

Both are keyword defaults on `run_pipeline` (`pipeline.py:54-55`).
The three call sites are wrapped:

- `pipeline.py:82` — `read_file_fn(fp, 1, 5000)` for diff augmentation
  (guard: `except (NotImplementedError, OSError)`)
- `pipeline.py:164` — `search_fn(...)` for existing-test lookup
  (guard: `except (NotImplementedError, Exception)`)
- `pipeline.py:173` — `read_file_fn(file_path, 1, 200)` for
  surrounding-context verification (same guard)

Filling the stubs converts those silent fallbacks into real
verification.

---

## 3. Anatomy of a Stub

Open `src/mellea_skills_compiler/examples/sentry-find-bugs/sentry_find_bugs_mellea/constrained_slots.py`.
The simpler of the two — `read_file_fn` (lines 27–42) — has a fixed
signature (call sites pass `(str, int, int)`), a fixed return type
(downstream code expects `str` for `grounding_context`), and a
docstring example that is the contract — the compiler captured it from
the spec:

```python
def read_file_fn(file_path: str, start_line: int, end_line: int) -> str:
    """Read lines start_line..end_line (1-indexed, inclusive) from file_path.

    TO IMPLEMENT: Replace this stub with a real file reading implementation.
    Example:

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[start_line - 1:end_line])
    """
    raise NotImplementedError(...)
```

`search_fn` (lines 6–24) follows the same shape with a
`subprocess.run(["grep", ...])` example.

---

## 4. Implement `read_file_fn`

The docstring's example is already a valid implementation. Drop it in
and remove the `raise`:

```python
def read_file_fn(file_path: str, start_line: int, end_line: int) -> str:
    """Read lines start_line..end_line (1-indexed, inclusive) from file_path."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[start_line - 1:end_line])
    except OSError:
        return ""
```

`errors="replace"` survives mixed-encoding files;
`lines[start_line - 1:end_line]` honours the 1-indexed inclusive
contract; `OSError → ""` mirrors the call-site guard so missing files
degrade gracefully. The call sites read at most 5000 lines
(`pipeline.py:82`) or 200 (`:173`) — bounded, no streaming.

`search_fn` is the second exercise; its docstring's
`subprocess.run(["grep", ...])` example also needs nothing beyond the
standard library.

---

## 5. Re-Run

`edge_comments_only` ships a tiny diff (under 500 chars) and a single
modified file `api/auth.py` — the most direct way to route through the
diff-augmentation path at `pipeline.py:82`:

```bash
mellea-skills run src/mellea_skills_compiler/examples/sentry-find-bugs/sentry_find_bugs_mellea \
  --fixture edge_comments_only
```

Predicted shape (the verdict on a docstring-only diff is "no issues",
mirroring the captured `clean_secure_parameterized` output):

```
issues=[]
reviewed_files=['api/auth.py']
checklist_summary={'Injection': 'clean', ...}
unverified_areas=[...]
```

The behavioural difference: with `read_file_fn` implemented, the
pipeline pulls the full contents of `api/auth.py` into the diff before
Phase 2 instead of running Phase 2 on the bare comment hunk. On a real
audit, that is what turns "Authentication: unverified" into a real
verdict.

---

## 6. Troubleshooting

- **`FileNotFoundError` escapes your stub.** Return `""` on the error
  path; the wrapped `try/except` at `pipeline.py:84` and `:174` treats
  this as "no context available".
- **`TypeError: unexpected keyword argument`.** A parameter was renamed
  or reordered. Restore `(file_path, start_line, end_line)` positional.
- **Same `unverified` categories as before.** The fixture's diff is too
  large to enter the augmentation path (gated on `len(diff) < 500`).
  Use `edge_comments_only` or `edge_empty_diff` to force it.
- **`ConnectionError` from the smoke check itself.** Ollama is
  unreachable. The smoke check classifies this as `skipped` not
  `failed`; bring the backend up and retry.

---

## What's Next

Once your compiled skill runs cleanly, see [`EXPORTING.md`](EXPORTING.md) for how to integrate it with other agent harnesses (manual integration today; native MCP / LangGraph / Claude Code exporters are on the roadmap).

## Reference

- Stub catalogue: `SETUP.md §8` inside `sentry_find_bugs_mellea/`
- Smoke check verdicts: `src/mellea_skills_compiler/compile/smoke_check.py`
- Fixture loader: `src/mellea_skills_compiler/toolkit/file_utils.py`
- Compile-time deny rules: `src/mellea_skills_compiler/compile/writer_renderer.py`
- Exporting compiled skills: [`EXPORTING.md`](EXPORTING.md)
