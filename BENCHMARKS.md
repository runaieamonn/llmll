# Token-cost benchmark: llmll vs Python

Equivalent programs in llmll and idiomatic Python, measured against production tokenizers.

## Per-program token counts

| program        | py  | llmll (formatted) | llmll (compact) | compact vs py |
| -------------- | --- | ----------------- | --------------- | ------------- |
| factorial      | 28  | 71 / 70           | 60 / 60         | +114% / +114% |
| fib            | 32  | 85 / 84           | 72 / 72         | +125% / +125% |
| fizzbuzz       | 59  | 126 / 125         | 106 / 107       | +80% / +81%   |
| sum_of_squares | 24  | 124 / 124         | 105 / 108       | +338% / +350% |
| word_count     | 17  | 24 / 23           | 22 / 21         | +29% / +24%   |
| find_max       | 35  | 73 / 72           | 57 / 57         | +63% / +63%   |
| count_vowels   | 18  | 78 / 77           | 63 / 67         | +250% / +272% |
| **TOTAL**      | 213 | 581 / 575         | 485 / 492       | **+128% / +131%** |

Each cell shows `cl100k_base / o200k_base`. The two OpenAI encodings agree closely.

## One-time spec overhead

| tokenizer          | SPEC.md | schema.json |
| ------------------ | ------- | ----------- |
| OpenAI cl100k_base | 1883    | 462         |
| OpenAI o200k_base  | 1885    | 465         |

## Break-even

| tokenizer          | savings/program (compact llmll vs py) | break-even N programs       |
| ------------------ | -------------------------------------- | --------------------------- |
| OpenAI cl100k_base | -38.9                                  | never (loses 38.9 tok/prog) |
| OpenAI o200k_base  | -39.9                                  | never (loses 39.9 tok/prog) |

llmll is more verbose per program *and* has a 1.9k-token spec to include. There is no number of programs after which including the spec pays back.

## Anthropic and Gemini

Not yet measured. Both require API keys (`ANTHROPIC_API_KEY` and `GEMINI_API_KEY`/`GOOGLE_API_KEY`). Both Anthropic (BPE) and Gemini (SentencePiece) tokenize JSON broadly the way GPT tokenizers do, so the conclusion is unlikely to flip — but the Gemini result in particular is worth confirming because SentencePiece treats punctuation differently than BPE.

To re-run with API keys present:

```bash
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
.venv/bin/python benchmarks/measure.py
```

## Why llmll loses on tokens

Two structural reasons that nothing in the current design can fix:

1. **Per-node syntactic overhead.** Every operation in llmll costs `[`, `"op"`, `,`, `,`, `]` — five tokens of pure framing per call site, plus the comma-separators between args. Python's infix operators (`+`, `==`, `*`) are 1 token each. A nested expression with N operations pays ~5N tokens of framing in llmll vs N tokens in Python.

2. **Comprehensions are pathologically token-dense in Python.** `sum(x*x for x in range(1,11) if x%2==0)` is 24 tokens. The llmll equivalent (`reduce` + `map` + `filter` + lambdas, all wrapped in JSON arrays) is 105 tokens — over 4x. Modern BPE tokenizers learned to merge Python comprehension idioms into very short token sequences. We cannot beat that without parsing infix syntax — which would defeat the constrained-decoding-makes-syntax-errors-impossible property.

3. **Variable references cost a sigil.** `"$x"` is typically 2 tokens; `x` is 1. This is small, but multiplied across every reference it adds up.

## What llmll still uniquely offers

The project is not pointless — but its value proposition is not "fewer tokens." What it actually delivers, that Python cannot:

- **Syntactic errors are unrepresentable.** With JSON-mode / structured decoding, the model literally cannot emit a malformed program. Python lets you generate `def foo(:` and only finds out at parse time.
- **Homoiconicity.** Programs and values are the same data type. A program can produce a program; an LLM can inspect, transform, and emit programs as data.
- **Inspectable closures.** A function value is `["closure", env, params, body]` — fully visible, fully serializable. In Python, a closure is opaque.
- **Predictable in-context learnability.** A model that has *never seen* llmll can write it from a one-page spec, because the rules fit in working memory. A new dialect of Python could not make that claim.
- **Schema-validated programs at rest.** llmll programs can be checked, diffed, transformed by tooling that understands JSON Schema. Python source can't.

## Implication

If raw tokens were the only metric, this design would be wrong. The honest reframing is: **llmll trades roughly 2x token cost for guaranteed-valid, schema-checkable, homoiconic programs.** Whether that trade is worth it depends entirely on the use case:

- **Worth it**: agent code execution where syntactic correctness on first try matters more than token cost; long-lived programs that get inspected and transformed; settings where the same program is generated and re-used.
- **Not worth it**: one-shot code generation where Python works fine and the LLM rarely makes syntax mistakes anyway.
