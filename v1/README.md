# llmll v1 — auditable LLM reasoning traces

A notation for LLM reasoning that is simultaneously the medium of decision-making and the audit document.

A trace is a YAML list of typed steps (`observe`, `rule`, `infer`, `consider`, `decide`), each with explicit provenance (`from`, `via`) and probabilistic confidence. The verifier rebuilds the world from observations, re-evaluates every claimed inference against its cited premises and rule, recomputes confidence under the rule's combination strategy, and confirms that every rejected candidate genuinely fails its rejecting rule.

## Quickstart

```bash
.venv/bin/python v1/verifier.py v1/examples/restaurant_recommendation.yaml
.venv/bin/python -m unittest discover v1/tests
```

## Files

- `SPEC.md` — language reference: step kinds, fields, expression sublanguage, semantics, verification rules.
- `examples/restaurant_recommendation.yaml` — hand-authored trace: chooses a restaurant from 5 candidates, rejects 3 explicitly with cited rules, decides between the 2 surviving candidates by rating.
- `verifier.py` — parser + checker (~430 LOC, single file). Loads YAML, walks steps in document order, verifies each.
- `tests/test_verifier.py` — 20 tests including 12 adversarial cases (tampered confidence, uncited premises, invalid rejections, etc.).

## What the verifier guarantees

A trace that passes verification is guaranteed to be **internally consistent**:
- Every cited premise actually exists.
- Every claimed derivation actually fires (the rule body evaluates to true under the cited binding, using only cited premises).
- Every confidence value is consistent with its inputs under the stated combination strategy (within tolerance).
- Every rejected candidate genuinely fails its rejecting rule.

It does **not** guarantee:
- The rules themselves are correct (that's a domain-knowledge question).
- Observations are accurate (that's a sensing / data quality question).
- The decision is a "good" one in any normative sense.

The verifier confirms the LLM's reasoning is valid given its inputs. The auditor still has to evaluate whether the inputs and rules deserve trust.

## Status

v1 prototype, 2026-05-03. Restaurant-recommendation domain works end-to-end.

## Related

See `../BENCHMARKS.md` for the v0 token-cost study that motivated the v1 pivot away from "token-efficient computation" toward "auditable reasoning traces."
