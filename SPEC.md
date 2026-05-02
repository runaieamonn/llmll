# llmll language reference

llmll is a programming language for LLMs. A program is a JSON value, executed by an interpreter.

## Surface syntax

Every llmll program is a JSON value. There is no parser beyond a JSON parser.

There are exactly three kinds of expression:

1. **Literals** — `null`, `true`, `false`, any number, any string that does not start with `$`, any object, and any array whose first element is *not* a string. Literals evaluate to themselves. Their inner elements are **not** recursively evaluated.
2. **Variable references** — a string starting with `$`, e.g., `"$x"`. Evaluates to the value of `x`. Look up first in the local environment, then in the global environment. Unbound is an error.
3. **Calls** — an array whose first element is a *literal string* matching an operator name: `[op, arg1, arg2, ...]`. The operator decides how the arguments are evaluated.

That is the entire syntax.

### Important consequence

Because *any* array whose first element is a string is a call, a literal list of strings cannot be written as a JSON array literal. Use the `list` constructor:

- `[1, 2, 3]` → literal list of numbers (first element is `1`, not a string).
- `["a", "b", "c"]` → would be parsed as a call to operator `"a"`. This is **not** a list of strings.
- `["list", "a", "b", "c"]` → list of three strings.

For lists whose elements are mixed or are not all strings, the array literal works as long as the first element is not a string: `[1, "x", true]` is fine.

## Values

Every runtime value is a JSON value:

- `null`, booleans, numbers, strings, arrays (called *lists*), objects (called *dicts*).
- **Closures**: `["closure", env, params, body]` — a 4-element list produced by evaluating `lambda`. `env` is a dict of captured local bindings; `params` is a list of parameter names; `body` is an expression.
- **Errors**: `["error", message]` — produced by `try` when an evaluation fails.

Closures and errors are not separate types — they are ordinary lists with a known shape. They can be inspected, serialized, and constructed by data manipulation.

## Truthiness

Falsy: `false`, `null`, `0`, `""`, `[]`, `{}`. Everything else is truthy.

## Special forms

These have non-standard evaluation rules:

| Form | Behavior |
|---|---|
| `["if", cond, then, else]` | Evaluate `cond`. If truthy, evaluate and return `then`; else `else`. |
| `["let", [[name, expr], ...], body]` | Sequentially evaluate each `expr`, bind to `name` in a new local frame, then evaluate `body`. Bindings are *not* recursive. |
| `["lambda", [param, ...], body]` | Capture the current local environment; produce a closure. |
| `["def", name, value]` | Evaluate `value`, bind to `name` in the global environment. Returns `null`. |
| `["do", e1, e2, ...]` | Evaluate each in order; return the last. Used for sequenced I/O. |
| `["try", expr]` | Evaluate `expr`. If it raises, return `["error", message]`; else return its value. |
| `["call", fn, arg, ...]` | Evaluate `fn` (must yield a closure), evaluate args, apply. |
| `["and", e1, e2, ...]` | Short-circuit: return the first falsy result, else the last. |
| `["or", e1, e2, ...]` | Short-circuit: return the first truthy result, else the last. |
| `["not", e]` | Boolean negation. |

## Operators

All operators evaluate their arguments left-to-right and apply the named primitive.

**Arithmetic** (numbers): `add` (n-ary, identity 0), `sub` (binary), `mul` (n-ary, identity 1), `div` (binary), `mod` (binary), `neg` (unary).

**Comparison** (binary, return bool): `eq`, `ne`, `lt`, `gt`, `le`, `ge`. `eq`/`ne` compare any JSON values structurally; ordering ops require numbers or strings.

**Lists**:
- `["list", v1, v2, ...]` — list from evaluated values.
- `["len", x]` — length of list, string, or dict.
- `["get", coll, key]` — `list[i]`, `dict[k]`, or `string[i]`.
- `["append", list, v]` — new list with `v` added at end.
- `["concat", a, b]` — concatenate two lists or two strings.
- `["slice", x, start, end]` — sub-list or sub-string.
- `["range", start, end]` — `[start, start+1, ..., end-1]`.
- `["map", fn, list]` — apply closure `fn` to each element.
- `["filter", fn, list]` — keep elements where `fn` returns truthy.
- `["reduce", fn, init, list]` — left fold; `fn` takes `(acc, elem)`.

**Dicts**:
- `["dict", k1, v1, k2, v2, ...]` — dict from alternating computed key/value pairs.
- `["keys", d]` — list of keys.
- `["vals", d]` — list of values.
- `["has", d, key]` — bool.
- `["put", d, key, value]` — new dict with the key set.

**Strings**:
- `["str", v1, v2, ...]` — convert each value to its string form, concatenate.
- `["split", s, sep]` — list of substrings.
- `["join", list, sep]` — concatenate list elements (as strings) with separator.

(`len`, `get`, `slice` work on strings too.)

**Type**:
- `["type", v]` — returns `"null"`, `"bool"`, `"num"`, `"str"`, `"list"`, `"dict"`, `"closure"`, or `"error"`.

**I/O**:
- `["print", v]` — print `v` (in its string form) to host output. Returns `null`.
- `["read"]` — read one line from host input. Returns string.

## Errors

An operation raises an error on: unknown operator, unbound variable, arity mismatch, type mismatch, division by zero, out-of-bounds access, key-not-found. An uncaught error aborts the program. `["try", expr]` converts an error into the value `["error", message]`.

## Recursion

Use `def` to define recursive functions. `let` bindings are not recursive: a closure produced inside `let` does not see later `let` bindings.

```json
["def", "fact", ["lambda", ["n"],
  ["if", ["le", "$n", 1], 1,
    ["mul", "$n", ["call", "$fact", ["sub", "$n", 1]]]]]]
```

## Worked example

Sum of squares of even numbers in `[1..10]`:

```json
["do",
  ["def", "nums", ["range", 1, 11]],
  ["def", "evens", ["filter", ["lambda", ["x"], ["eq", ["mod", "$x", 2], 0]], "$nums"]],
  ["def", "sq", ["map", ["lambda", ["x"], ["mul", "$x", "$x"]], "$evens"]],
  ["print", ["reduce", ["lambda", ["a", "b"], ["add", "$a", "$b"]], 0, "$sq"]]]
```

Output: `220`.

## Mental model summary

- A program is a JSON value.
- Strings starting with `$` are variables; everything else stringy is a literal string.
- Arrays whose first element is a string are calls; everything else is data.
- All values are JSON; closures and errors are tagged lists.
- Computation is functional; `do` and `def` introduce ordered effects.
- Errors abort unless wrapped in `try`.
