# llmll v1 — reasoning trace language

llmll v1 is a notation for **LLM reasoning traces**. A trace is both:
1. The medium an LLM thinks in when making a decision, and
2. A document that humans (or other LLMs) can audit to understand why and how the decision was made.

A trace is a YAML file containing an ordered list of **steps**. Each step is a self-describing block with a `kind`, an `id`, the step-specific content, and provenance metadata.

## Step kinds

| kind | purpose | notable fields |
|---|---|---|
| `observe` | introduce facts from outside the trace (user input, sensors, databases) | `facts`, `src`, `conf` |
| `rule` | declare a domain rule that derives conclusions from premises | `head`, `body`, `conf`, optional `combine` |
| `infer` | apply a rule to cited premises to derive a new fact | `conclusion`, `from`, `via`, `conf` |
| `consider` | record a candidate that was evaluated and rejected | `candidate`, `rejected_by`, optional `reason` |
| `decide` | commit to a final choice; cites supporting inferences | `conclusion`, `from`, `via`, `conf`, optional `reason`, `caveat` |

Every step has:
- **`id`** — a unique string handle. Other steps reference this id in their `from` / `via` / `rejected_by` fields. The trace is therefore a directed acyclic graph of provenance.
- **`kind`** — one of the five above.

## Provenance vocabulary (mapped to PROV-O)

| llmll | PROV-O analog |
|---|---|
| `observe` | `prov:wasGeneratedBy` (the source) |
| `rule` | `prov:Plan` (a strategy that drives derivation) |
| `infer` | `prov:wasDerivedFrom` (premises) + `prov:wasInformedBy` (rule) |
| `decide` | `prov:Activity` producing a `prov:Entity` |
| `consider` / `rejected_by` | extension — PROV-O has no "considered and rejected" concept |
| `caveat` | `prov:wasQualifiedBy` (extended) |

## Confidence and combination

Every `observe`, `rule`, `infer`, and `decide` carries a `conf` value in `[0, 1]`. Confidences propagate through inferences according to the rule's `combine` strategy:

| `combine` | computation | when to use |
|---|---|---|
| `product` (default) | `∏(premise_conf) × rule_conf` | premises are independent |
| `min` | `min(min(premise_conf), rule_conf)` | pessimistic / weakest-link |
| `noisy_and` | `1 - ∏(1 - premise_conf) × rule_conf` | premises reinforce each other |

The verifier checks that the `conf` stated on an `infer` is consistent with the combination function applied to the premise confidences and the rule confidence, within a tolerance (default ±0.05).

## File format

A trace is a YAML document containing a list of step mappings:

```yaml
- id: o1
  kind: observe
  facts:
    user:
      cuisine: "italian"
  src: query
  conf: 1.0

- id: r_cuisine
  kind: rule
  head: cuisine_match(R)
  body: R.cuisine == user.cuisine
  conf: 0.95

- id: i1
  kind: infer
  conclusion: cuisine_match(r1)
  from: [o10, o1]
  via: r_cuisine
  conf: 0.81
```

YAML chosen because it self-labels every field (essential for human auditing), it's in the LLM's native fluency, and it parses with one library call.

## Step-by-step semantics

### `observe`

Introduces facts into the **world** — the set of ground attribute facts known to the trace. Facts are nested under entity names:

```yaml
facts:
  user:
    cuisine: "italian"
    budget: 80
  r1:
    name: "Tony's"
    cuisine: "italian"
    price: 45
```

After this step, the world contains `world.user.cuisine == "italian"`, `world.r1.name == "Tony's"`, etc. Multiple observations may extend the same entity.

`src` is a free-form string identifying the origin (e.g. `"query"`, `"gps"`, `"yelp:r1"`, `"chart"`, a URL). `conf` is the confidence in the observation itself (e.g., GPS = 0.99, third-party reviews = 0.85).

### `rule`

Declares a **derivation rule**: a `head` predicate that holds whenever the `body` expression evaluates to true.

```yaml
- id: r_cuisine
  kind: rule
  head: cuisine_match(R)
  body: R.cuisine == user.cuisine
  conf: 0.95
```

- `head` is a predicate-call form `name(var1, var2, ...)`. The variables are universal — when the rule fires, they bind to ground entities.
- `body` is a Boolean expression over the world and any predicates already derived. Body may reference the head's variables.
- `conf` is how reliably the rule itself holds (separate from confidence in any particular firing).
- `combine` (optional) picks the propagation strategy.

Rules are pure declarations — they don't fire automatically. `infer` steps explicitly fire them.

### `infer`

Claims that a rule, applied to specific cited premises, produces a specific conclusion with a specific confidence.

```yaml
- id: i1
  kind: infer
  conclusion: cuisine_match(r1)
  from: [o10, o1]
  via: r_cuisine
  conf: 0.81
```

The verifier:
1. Looks up the rule named in `via`.
2. Matches `conclusion` against the rule's `head` to recover the variable binding (e.g., `R = r1`).
3. Substitutes that binding into the rule's `body`.
4. Evaluates the body using the cited premises — any attribute or predicate referenced must come from a step listed in `from`. Citing irrelevant or missing premises is an error.
5. Confirms the body evaluates to true (the rule actually fires).
6. Recomputes the expected confidence under the rule's `combine` strategy.
7. Flags a discrepancy if `|expected - stated| > tolerance`.

### `consider`

Records a candidate that was evaluated and **not chosen**. This is the major addition over PROV-O: an honest audit log shows what was considered and rejected, not just what was chosen.

```yaml
- id: c_r3
  kind: consider
  candidate: r3
  rejected_by: r_cuisine
  reason: "r3.cuisine is 'japanese', user wants 'italian'"
```

The verifier checks that, under the rejecting rule's body with the candidate substituted, the body evaluates to **false** — i.e., the rule genuinely does *not* fire for this candidate. Free-text `reason` is preserved for human readers; not checked.

### `decide`

The final commitment.

```yaml
- id: d1
  kind: decide
  conclusion: recommend == r1
  from: [i_r1_good, i_r2_good]
  via: rank_by_rating
  conf: 0.62
  reason: "r1 (4.6) outranks r2 (4.4); both meet hard criteria"
  caveat: "r2 may be preferred for larger party or different atmosphere"
```

A decision is more than a rule firing — it's a meta-level choice over candidates. The verifier checks that:
- All `from` references resolve to existing steps.
- The chosen entity in `conclusion` appears in the supporting inferences.
- `conf` is plausible (≤ min of premise confs).

`reason` and `caveat` are free text for the human auditor; not formally checked.

## Expression sublanguage

`fact`, `body`, and `conclusion` field values containing expressions are parsed as Python expression syntax (i.e., `ast.parse(..., mode='eval')`) and restricted to a safe subset:

- **Literals**: numbers, strings, booleans, `None`, lists, dicts.
- **Names**: identifiers (looked up in the world / binding context).
- **Attribute access**: `user.cuisine`, `R.loc`.
- **Subscript**: `R.hours[0]`.
- **Comparisons**: `==`, `!=`, `<`, `<=`, `>`, `>=`.
- **Boolean**: `and`, `or`, `not`.
- **Arithmetic**: `+`, `-`, `*`, `/`, `%`.
- **Function calls**: only to whitelisted built-ins (see below).

Calling Python attributes / methods other than dotted-attribute access on world entities is rejected.

## Built-in functions

| name | signature | purpose |
|---|---|---|
| `distance_km(loc1, loc2)` | `[lat, lon] × [lat, lon] → float` | great-circle distance |
| `len(x)` | `list \| str → int` | length |
| `abs(x)` | `num → num` | absolute value |
| `min(x, y)` / `max(x, y)` | binary | min / max |

Add others as needed; the spec is open in this dimension because the built-in set is what makes the language useful in any given domain.

## Verification

A trace is **valid** if all of the following hold:
1. **Structural**: every step has the required fields for its kind; ids are unique; references resolve.
2. **DAG**: no cycles in `from` / `via` references (derivations must reach back to observations).
3. **Inference soundness**: for every `infer` step, the rule applied with the cited binding actually fires under the cited premises (recomputed by the verifier).
4. **Confidence consistency**: every stated `conf` matches the recomputed value under the rule's `combine` strategy, within tolerance.
5. **Rejection soundness**: for every `consider` step, the rejecting rule does not fire for the candidate.
6. **Decision plausibility**: `decide` premises exist and the chosen conclusion is among the supported candidates.

A valid trace is a machine-checkable proof that the LLM's reasoning is internally consistent given its observations and rules. It does **not** prove the rules themselves are correct, or that observations are accurate — those are the human auditor's job.
