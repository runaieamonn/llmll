"""llmll: a JSON programming language for LLMs."""

import json
import sys


class LlmllError(Exception):
    pass


GLOBAL = {}


def evaluate(expr, env):
    if expr is None or isinstance(expr, bool):
        return expr
    if isinstance(expr, (int, float)):
        return expr
    if isinstance(expr, str):
        if expr.startswith("$"):
            name = expr[1:]
            if name in env:
                return env[name]
            if name in GLOBAL:
                return GLOBAL[name]
            raise LlmllError(f"unbound variable: {name}")
        return expr
    if isinstance(expr, dict):
        return expr
    if isinstance(expr, list):
        if len(expr) == 0:
            return expr
        first = expr[0]
        if isinstance(first, str):
            return apply_call(first, expr[1:], env)
        return expr
    raise LlmllError(f"cannot evaluate value of type {type(expr).__name__}")


def apply_call(op, args, env):
    sf = SPECIAL_FORMS.get(op)
    if sf is not None:
        return sf(args, env)
    fn = OPS.get(op)
    if fn is not None:
        evaluated = [evaluate(a, env) for a in args]
        return fn(evaluated)
    raise LlmllError(f"unknown operator: {op}")


def truthy(v):
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0:
        return False
    if isinstance(v, str) and v == "":
        return False
    if isinstance(v, list) and len(v) == 0:
        return False
    if isinstance(v, dict) and len(v) == 0:
        return False
    return True


def is_closure(v):
    return isinstance(v, list) and len(v) == 4 and v[0] == "closure"


def apply_closure(fn, arg_vals):
    if not is_closure(fn):
        raise LlmllError(f"not a closure: {fn!r}")
    _, captured, params, body = fn
    if len(arg_vals) != len(params):
        raise LlmllError(
            f"arity mismatch: expected {len(params)}, got {len(arg_vals)}"
        )
    new_env = dict(captured)
    for p, v in zip(params, arg_vals):
        new_env[p] = v
    return evaluate(body, new_env)


# --- special forms ---


def sf_if(args, env):
    if len(args) != 3:
        raise LlmllError("if: expected 3 args")
    cond, then, els = args
    return evaluate(then if truthy(evaluate(cond, env)) else els, env)


def sf_let(args, env):
    if len(args) != 2:
        raise LlmllError("let: expected 2 args")
    bindings, body = args
    if not isinstance(bindings, list):
        raise LlmllError("let: bindings must be a list")
    new_env = dict(env)
    for b in bindings:
        if not (isinstance(b, list) and len(b) == 2 and isinstance(b[0], str)):
            raise LlmllError(f"let: bad binding: {b!r}")
        new_env[b[0]] = evaluate(b[1], new_env)
    return evaluate(body, new_env)


def sf_lambda(args, env):
    if len(args) != 2:
        raise LlmllError("lambda: expected 2 args")
    params, body = args
    if not (isinstance(params, list) and all(isinstance(p, str) for p in params)):
        raise LlmllError("lambda: params must be a list of strings")
    return ["closure", dict(env), params, body]


def sf_def(args, env):
    if len(args) != 2:
        raise LlmllError("def: expected 2 args")
    name, value_expr = args
    if not isinstance(name, str):
        raise LlmllError("def: name must be a string")
    GLOBAL[name] = evaluate(value_expr, env)
    return None


def sf_do(args, env):
    result = None
    for e in args:
        result = evaluate(e, env)
    return result


def sf_try(args, env):
    if len(args) != 1:
        raise LlmllError("try: expected 1 arg")
    try:
        return evaluate(args[0], env)
    except LlmllError as e:
        return ["error", str(e)]


def sf_call(args, env):
    if len(args) < 1:
        raise LlmllError("call: expected at least 1 arg (the function)")
    fn = evaluate(args[0], env)
    arg_vals = [evaluate(a, env) for a in args[1:]]
    return apply_closure(fn, arg_vals)


def sf_and(args, env):
    result = True
    for e in args:
        result = evaluate(e, env)
        if not truthy(result):
            return result
    return result


def sf_or(args, env):
    result = False
    for e in args:
        result = evaluate(e, env)
        if truthy(result):
            return result
    return result


SPECIAL_FORMS = {
    "if": sf_if,
    "let": sf_let,
    "lambda": sf_lambda,
    "def": sf_def,
    "do": sf_do,
    "try": sf_try,
    "call": sf_call,
    "and": sf_and,
    "or": sf_or,
}


# --- ordinary operators (args already evaluated) ---


def _check_num(op, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise LlmllError(f"{op}: not a number: {v!r}")


def op_not(a):
    _arity("not", a, 1)
    return not truthy(a[0])


def op_add(a):
    for v in a:
        _check_num("add", v)
    return sum(a) if a else 0


def op_sub(a):
    _arity("sub", a, 2)
    _check_num("sub", a[0])
    _check_num("sub", a[1])
    return a[0] - a[1]


def op_mul(a):
    for v in a:
        _check_num("mul", v)
    r = 1
    for v in a:
        r *= v
    return r


def op_div(a):
    _arity("div", a, 2)
    _check_num("div", a[0])
    _check_num("div", a[1])
    if a[1] == 0:
        raise LlmllError("div: division by zero")
    return a[0] / a[1]


def op_mod(a):
    _arity("mod", a, 2)
    _check_num("mod", a[0])
    _check_num("mod", a[1])
    if a[1] == 0:
        raise LlmllError("mod: division by zero")
    return a[0] % a[1]


def op_neg(a):
    _arity("neg", a, 1)
    _check_num("neg", a[0])
    return -a[0]


def op_eq(a):
    _arity("eq", a, 2)
    return a[0] == a[1]


def op_ne(a):
    _arity("ne", a, 2)
    return a[0] != a[1]


def _orderable(op, v):
    if isinstance(v, bool):
        raise LlmllError(f"{op}: cannot order booleans")
    if not isinstance(v, (int, float, str)):
        raise LlmllError(f"{op}: cannot order {type(v).__name__}")


def op_lt(a):
    _arity("lt", a, 2)
    _orderable("lt", a[0]); _orderable("lt", a[1])
    return a[0] < a[1]


def op_gt(a):
    _arity("gt", a, 2)
    _orderable("gt", a[0]); _orderable("gt", a[1])
    return a[0] > a[1]


def op_le(a):
    _arity("le", a, 2)
    _orderable("le", a[0]); _orderable("le", a[1])
    return a[0] <= a[1]


def op_ge(a):
    _arity("ge", a, 2)
    _orderable("ge", a[0]); _orderable("ge", a[1])
    return a[0] >= a[1]


def op_list(a):
    return list(a)


def op_len(a):
    _arity("len", a, 1)
    v = a[0]
    if isinstance(v, (list, str, dict)):
        return len(v)
    raise LlmllError(f"len: {type(v).__name__} has no length")


def op_get(a):
    _arity("get", a, 2)
    coll, key = a
    if isinstance(coll, list):
        if isinstance(key, bool) or not isinstance(key, int):
            raise LlmllError("get: list index must be integer")
        if key < 0 or key >= len(coll):
            raise LlmllError(f"get: index {key} out of range (len {len(coll)})")
        return coll[key]
    if isinstance(coll, dict):
        if not isinstance(key, str):
            raise LlmllError("get: dict key must be string")
        if key not in coll:
            raise LlmllError(f"get: key not found: {key!r}")
        return coll[key]
    if isinstance(coll, str):
        if isinstance(key, bool) or not isinstance(key, int):
            raise LlmllError("get: string index must be integer")
        if key < 0 or key >= len(coll):
            raise LlmllError(f"get: string index {key} out of range")
        return coll[key]
    raise LlmllError(f"get: not indexable: {type(coll).__name__}")


def op_append(a):
    _arity("append", a, 2)
    if not isinstance(a[0], list):
        raise LlmllError("append: first arg must be list")
    return a[0] + [a[1]]


def op_concat(a):
    _arity("concat", a, 2)
    x, y = a
    if isinstance(x, list) and isinstance(y, list):
        return x + y
    if isinstance(x, str) and isinstance(y, str):
        return x + y
    raise LlmllError("concat: args must be both lists or both strings")


def op_slice(a):
    _arity("slice", a, 3)
    x, start, end = a
    if not isinstance(x, (list, str)):
        raise LlmllError("slice: first arg must be list or string")
    if isinstance(start, bool) or not isinstance(start, int):
        raise LlmllError("slice: start must be integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise LlmllError("slice: end must be integer")
    return x[start:end]


def op_range(a):
    _arity("range", a, 2)
    if isinstance(a[0], bool) or not isinstance(a[0], int):
        raise LlmllError("range: start must be integer")
    if isinstance(a[1], bool) or not isinstance(a[1], int):
        raise LlmllError("range: end must be integer")
    return list(range(a[0], a[1]))


def op_map(a):
    _arity("map", a, 2)
    fn, lst = a
    if not isinstance(lst, list):
        raise LlmllError("map: second arg must be list")
    return [apply_closure(fn, [x]) for x in lst]


def op_filter(a):
    _arity("filter", a, 2)
    fn, lst = a
    if not isinstance(lst, list):
        raise LlmllError("filter: second arg must be list")
    return [x for x in lst if truthy(apply_closure(fn, [x]))]


def op_reduce(a):
    _arity("reduce", a, 3)
    fn, init, lst = a
    if not isinstance(lst, list):
        raise LlmllError("reduce: third arg must be list")
    acc = init
    for x in lst:
        acc = apply_closure(fn, [acc, x])
    return acc


def op_dict(a):
    if len(a) % 2 != 0:
        raise LlmllError("dict: expected even number of args (alternating key/value)")
    d = {}
    for i in range(0, len(a), 2):
        k, v = a[i], a[i + 1]
        if not isinstance(k, str):
            raise LlmllError(f"dict: key must be string, got {type(k).__name__}")
        d[k] = v
    return d


def op_keys(a):
    _arity("keys", a, 1)
    if not isinstance(a[0], dict):
        raise LlmllError("keys: arg must be dict")
    return list(a[0].keys())


def op_vals(a):
    _arity("vals", a, 1)
    if not isinstance(a[0], dict):
        raise LlmllError("vals: arg must be dict")
    return list(a[0].values())


def op_has(a):
    _arity("has", a, 2)
    if not isinstance(a[0], dict):
        raise LlmllError("has: first arg must be dict")
    if not isinstance(a[1], str):
        raise LlmllError("has: key must be string")
    return a[1] in a[0]


def op_put(a):
    _arity("put", a, 3)
    d, key, value = a
    if not isinstance(d, dict):
        raise LlmllError("put: first arg must be dict")
    if not isinstance(key, str):
        raise LlmllError("put: key must be string")
    new_d = dict(d)
    new_d[key] = value
    return new_d


def to_str(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, str):
        return v
    return json.dumps(v, separators=(",", ":"))


def op_str(a):
    return "".join(to_str(v) for v in a)


def op_split(a):
    _arity("split", a, 2)
    s, sep = a
    if not (isinstance(s, str) and isinstance(sep, str)):
        raise LlmllError("split: args must be strings")
    return s.split(sep) if sep != "" else list(s)


def op_join(a):
    _arity("join", a, 2)
    lst, sep = a
    if not isinstance(lst, list):
        raise LlmllError("join: first arg must be list")
    if not isinstance(sep, str):
        raise LlmllError("join: separator must be string")
    return sep.join(to_str(x) for x in lst)


def op_type(a):
    _arity("type", a, 1)
    v = a[0]
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, list):
        if is_closure(v):
            return "closure"
        if len(v) >= 1 and v[0] == "error":
            return "error"
        return "list"
    return "unknown"


def op_print(a):
    _arity("print", a, 1)
    print(to_str(a[0]))
    return None


def op_read(a):
    _arity("read", a, 0)
    try:
        return input()
    except EOFError:
        return ""


def _arity(name, args, n):
    if len(args) != n:
        raise LlmllError(f"{name}: expected {n} args, got {len(args)}")


OPS = {
    "not": op_not,
    "add": op_add, "sub": op_sub, "mul": op_mul, "div": op_div, "mod": op_mod, "neg": op_neg,
    "eq": op_eq, "ne": op_ne, "lt": op_lt, "gt": op_gt, "le": op_le, "ge": op_ge,
    "list": op_list, "len": op_len, "get": op_get, "append": op_append,
    "concat": op_concat, "slice": op_slice, "range": op_range,
    "map": op_map, "filter": op_filter, "reduce": op_reduce,
    "dict": op_dict, "keys": op_keys, "vals": op_vals, "has": op_has, "put": op_put,
    "str": op_str, "split": op_split, "join": op_join,
    "type": op_type,
    "print": op_print, "read": op_read,
}


def run(program):
    return evaluate(program, {})


def reset_global():
    GLOBAL.clear()


def main():
    if len(sys.argv) < 2:
        print("usage: llmll.py <program.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        program = json.load(f)
    result = run(program)
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
