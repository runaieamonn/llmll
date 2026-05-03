"""Tokenizer comparison: llmll vs Python.

Counts tokens for equivalent programs in llmll and Python, against several
production tokenizers. tiktoken runs fully offline. Anthropic and Gemini
require API keys (ANTHROPIC_API_KEY, GEMINI_API_KEY or GOOGLE_API_KEY).
Tokenizers that fail to initialize are skipped with a note.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROGRAMS = [
    {
        "name": "factorial",
        "py": "def fact(n):\n    return 1 if n <= 1 else n * fact(n - 1)\nprint(fact(10))\n",
        "json": "examples/factorial.json",
    },
    {
        "name": "fib",
        "py": "def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\nprint(fib(12))\n",
        "json": "examples/fib.json",
    },
    {
        "name": "fizzbuzz",
        "py": (
            "for i in range(1, 16):\n"
            '    if i % 15 == 0: print("FizzBuzz")\n'
            '    elif i % 3 == 0: print("Fizz")\n'
            '    elif i % 5 == 0: print("Buzz")\n'
            "    else: print(i)\n"
        ),
        "json": "examples/fizzbuzz.json",
    },
    {
        "name": "sum_of_squares",
        "py": "print(sum(x * x for x in range(1, 11) if x % 2 == 0))\n",
        "json": "examples/sum_of_squares.json",
    },
    {
        "name": "word_count",
        "py": 'print(len("the quick brown fox jumps over the lazy dog".split(" ")))\n',
        "json": "benchmarks/word_count.json",
    },
    {
        "name": "find_max",
        "py": "print(max([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]))\n",
        "json": "benchmarks/find_max.json",
    },
    {
        "name": "count_vowels",
        "py": 'print(sum(1 for c in "hello world" if c in "aeiou"))\n',
        "json": "benchmarks/count_vowels.json",
    },
]


def load_json_program(path):
    """Return (formatted, compact) versions of a JSON program."""
    raw = (ROOT / path).read_text()
    parsed = json.loads(raw)
    compact = json.dumps(parsed, separators=(",", ":"))
    return raw.rstrip("\n"), compact


def make_counters():
    """Return list of (name, callable_or_None) for each tokenizer."""
    counters = []

    # OpenAI: cl100k_base (GPT-4 family) and o200k_base (GPT-4o, o1, o3 family)
    try:
        import tiktoken

        for enc_name in ("cl100k_base", "o200k_base"):
            enc = tiktoken.get_encoding(enc_name)
            counters.append((f"OpenAI {enc_name}", lambda t, e=enc: len(e.encode(t))))
    except Exception as e:
        counters.append(("OpenAI (tiktoken)", None, str(e)))

    # Anthropic: API-based count_tokens
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic

            client = anthropic.Anthropic()
            model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

            def count_anthropic(t, model=model, client=client):
                resp = client.messages.count_tokens(
                    model=model,
                    messages=[{"role": "user", "content": t}],
                )
                return resp.input_tokens

            counters.append((f"Anthropic ({model})", count_anthropic))
        except Exception as e:
            counters.append(("Anthropic", None, f"init failed: {e}"))
    else:
        counters.append(("Anthropic", None, "ANTHROPIC_API_KEY not set"))

    # Gemini: API-based count_tokens
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_key)
            model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

            def count_gemini(t, model=model, client=client):
                resp = client.models.count_tokens(model=model, contents=t)
                return resp.total_tokens

            counters.append((f"Gemini ({model})", count_gemini))
        except Exception as e:
            counters.append(("Gemini", None, f"init failed: {e}"))
    else:
        counters.append(("Gemini", None, "GEMINI_API_KEY/GOOGLE_API_KEY not set"))

    return counters


def render_table(rows, headers):
    widths = [
        max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))
    ]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    out = ["| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"]
    out.append(sep)
    for r in rows:
        out.append(
            "| "
            + " | ".join(str(r[i]).ljust(widths[i]) for i in range(len(headers)))
            + " |"
        )
    return "\n".join(out)


def main():
    counters = make_counters()
    active = [c for c in counters if len(c) == 2 and c[1] is not None]
    skipped = [(c[0], c[2]) for c in counters if len(c) == 3]

    print(f"Active tokenizers: {[c[0] for c in active]}")
    if skipped:
        print(f"Skipped: {skipped}")
    print()

    spec_text = (ROOT / "SPEC.md").read_text()
    schema_text = (ROOT / "schema.json").read_text()

    # --- per-program comparison ---
    headers = ["program"]
    for tok_name, _ in active:
        headers += [f"{tok_name} py", f"{tok_name} json", f"{tok_name} jsonc", "Δ%"]

    rows = []
    totals = {tok_name: {"py": 0, "json": 0, "jsonc": 0} for tok_name, _ in active}

    for prog in PROGRAMS:
        py = prog["py"]
        formatted, compact = load_json_program(prog["json"])
        row = [prog["name"]]
        for tok_name, count in active:
            n_py = count(py)
            n_json = count(formatted)
            n_jsonc = count(compact)
            delta_pct = (n_jsonc - n_py) * 100.0 / n_py
            row += [n_py, n_json, n_jsonc, f"{delta_pct:+.0f}%"]
            totals[tok_name]["py"] += n_py
            totals[tok_name]["json"] += n_json
            totals[tok_name]["jsonc"] += n_jsonc
        rows.append(row)

    # totals row
    total_row = ["TOTAL"]
    for tok_name, _ in active:
        t = totals[tok_name]
        delta_pct = (t["jsonc"] - t["py"]) * 100.0 / t["py"]
        total_row += [t["py"], t["json"], t["jsonc"], f"{delta_pct:+.0f}%"]
    rows.append(total_row)

    print("# Per-program token counts")
    print()
    print(
        "Columns: `py` = idiomatic Python source; `json` = formatted llmll (file as written); "
        "`jsonc` = compact llmll (no whitespace); `Δ%` = compact-llmll vs Python."
    )
    print()
    print(render_table(rows, headers))
    print()

    # --- spec overhead ---
    print("# One-time spec overhead")
    print()
    spec_rows = []
    for tok_name, count in active:
        spec_rows.append([tok_name, count(spec_text), count(schema_text)])
    print(render_table(spec_rows, ["tokenizer", "SPEC.md", "schema.json"]))
    print()

    # --- break-even analysis ---
    print("# Break-even: how many programs amortize the spec overhead?")
    print()
    print(
        "If llmll saves S tokens per program (compared to Python) and SPEC.md costs C tokens "
        "to include in the system prompt, then llmll is a net win after C/S programs."
    )
    print()
    be_rows = []
    for tok_name, count in active:
        n_spec = count(spec_text)
        t = totals[tok_name]
        per_prog_savings = (t["py"] - t["jsonc"]) / len(PROGRAMS)
        if per_prog_savings > 0:
            breakeven = n_spec / per_prog_savings
            be = f"{breakeven:.0f}"
        elif per_prog_savings == 0:
            be = "n/a (tied)"
        else:
            be = f"never (loses {-per_prog_savings:.1f} tok/prog)"
        be_rows.append(
            [tok_name, n_spec, f"{per_prog_savings:+.1f}", be]
        )
    print(
        render_table(
            be_rows,
            ["tokenizer", "spec tokens", "savings/prog (compact)", "break-even N programs"],
        )
    )


if __name__ == "__main__":
    main()
