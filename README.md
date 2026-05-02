# llmll

A programming language for LLMs, not humans.

A program is a JSON value, executed by an interpreter. The entire surface syntax is:

- **Literals** — `null`, `true`, `false`, numbers, strings (any string not starting with `$`), objects, and arrays whose first element is *not* a string.
- **Variable references** — strings starting with `$`, e.g., `"$x"`.
- **Calls** — arrays whose first element is a literal string operator name: `[op, arg, ...]`.

That's it. There is no parser beyond a JSON parser. Constrained-decoding APIs (Anthropic structured outputs, OpenAI JSON mode) can validate against `schema.json` to make syntactic errors *unrepresentable* at decode time.

## Quickstart

```bash
python3 llmll.py examples/factorial.json
# 3628800

python3 -m unittest discover tests
```

## Files

- `SPEC.md` — the language reference. One page; intended as a system-prompt input for an LLM.
- `schema.json` — JSON Schema for constrained decoding.
- `llmll.py` — the interpreter (~400 LOC, single file).
- `examples/` — sample programs.
- `tests/` — test suite.

## Design rationale

| Choice | Why |
|---|---|
| JSON arrays as the surface form | Token-efficient (close to S-expressions on BPE tokenizers); schema-validatable; native to LLM training. |
| Pure JSON values as the data model | Homoiconic: closures and errors are tagged lists. Any value is inspectable, serializable, transmittable. |
| Sigil for variables (`"$x"`) | One rule disambiguates variable references from literal strings. Costs ~0–1 extra tokens per ref. |
| Functional core + `do` for I/O | Pure semantics where it's free, sequencing where it's needed. |
| ~40 operators | Fits in a one-page spec for in-context learning, but big enough that simple tasks are one-liners. |
| No recursive `let`; recursion via `def` | Smaller spec; one obvious way to define recursive functions. |

## Status

v0 — interpreter complete; spec stable; not yet measured against tokenizers.
