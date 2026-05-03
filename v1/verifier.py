"""llmll v1 verifier.

Loads a YAML reasoning trace, rebuilds the world from observations, and
re-evaluates every claimed inference, rejection, and decision against its
cited premises and rule. Reports any structural, soundness, or confidence
discrepancies.

Usage:
    python verifier.py <trace.yaml>
"""

import ast
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# --- Built-in functions usable in expression bodies ---

def haversine_km(loc1, loc2):
    lat1, lon1 = loc1
    lat2, lon2 = loc2
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


BUILTINS = {
    "distance_km": haversine_km,
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
}


KIND_FIELDS = {
    "observe":  {"required": {"id", "kind", "facts", "src", "conf"}, "optional": set()},
    "rule":     {"required": {"id", "kind", "head", "body", "conf"}, "optional": {"combine"}},
    "infer":    {"required": {"id", "kind", "conclusion", "from", "via", "conf"}, "optional": set()},
    "consider": {"required": {"id", "kind", "candidate", "rejected_by"}, "optional": {"reason", "conf"}},
    "decide":   {"required": {"id", "kind", "conclusion", "from", "via", "conf"}, "optional": {"reason", "caveat"}},
}

VALID_COMBINE = {"product", "min"}
DEFAULT_COMBINE = "product"
DEFAULT_TOLERANCE = 0.05


# --- Issue reporting ---

@dataclass
class Issue:
    step_id: str
    severity: str  # "error" | "warning"
    message: str

    def __str__(self):
        return f"  [{self.severity.upper():7}] {self.step_id}: {self.message}"


@dataclass
class Report:
    issues: list = field(default_factory=list)
    n_steps: int = 0
    n_observe: int = 0
    n_rule: int = 0
    n_infer_checked: int = 0
    n_consider_checked: int = 0
    n_decide_checked: int = 0

    def add(self, issue):
        self.issues.append(issue)

    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]

    def ok(self):
        return len(self.errors()) == 0


# --- Expression evaluation ---

class EvalError(Exception):
    pass


class WorldEvaluator:
    """Evaluates a parsed expression against the world.

    Records the set of step IDs whose attributes or predicates were accessed
    during evaluation, so the caller can verify that all accesses were cited
    in the step's `from` list.
    """

    def __init__(self, world, attr_prov, predicates, bindings=None):
        self.world = world
        self.attr_prov = attr_prov          # {("entity","attr","sub"): step_id}
        self.predicates = predicates        # {("name", (args,)): {"step_id":..., "conf":...}}
        self.bindings = dict(bindings or {}) # {var_name: entity_name_or_value}
        self.accessed_steps = set()
        self._predicate_names = {p[0] for p in self.predicates}

    def eval(self, expr):
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise EvalError(f"syntax error in {expr!r}: {e}")
        return self._visit(tree.body)

    # ---- AST visit ----

    def _visit(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self._visit(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._visit(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return {self._visit(k): self._visit(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Name):
            return self._lookup_name(node.id)
        if isinstance(node, ast.Attribute):
            return self._lookup_attribute(node)
        if isinstance(node, ast.Subscript):
            value = self._visit(node.value)
            key = self._visit(node.slice)
            try:
                return value[key]
            except (KeyError, IndexError, TypeError) as e:
                raise EvalError(f"subscript {key!r} failed: {e}")
        if isinstance(node, ast.UnaryOp):
            v = self._visit(node.operand)
            if isinstance(node.op, ast.Not):  return not v
            if isinstance(node.op, ast.USub): return -v
            if isinstance(node.op, ast.UAdd): return +v
            raise EvalError(f"unsupported unary op: {type(node.op).__name__}")
        if isinstance(node, ast.BinOp):
            l, r = self._visit(node.left), self._visit(node.right)
            ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                   ast.Mod: lambda a, b: a % b, ast.FloorDiv: lambda a, b: a // b,
                   ast.Pow: lambda a, b: a ** b}
            op = ops.get(type(node.op))
            if op is None:
                raise EvalError(f"unsupported binary op: {type(node.op).__name__}")
            return op(l, r)
        if isinstance(node, ast.Compare):
            left = self._visit(node.left)
            for op_node, right_node in zip(node.ops, node.comparators):
                right = self._visit(right_node)
                ops = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
                       ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
                       ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b}
                op = ops.get(type(op_node))
                if op is None:
                    raise EvalError(f"unsupported compare op: {type(op_node).__name__}")
                if not op(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                last = True
                for v in node.values:
                    last = self._visit(v)
                    if not last:
                        return False
                return last
            if isinstance(node.op, ast.Or):
                last = False
                for v in node.values:
                    last = self._visit(v)
                    if last:
                        return last
                return False
            raise EvalError(f"unsupported bool op: {type(node.op).__name__}")
        if isinstance(node, ast.Call):
            return self._call(node)
        raise EvalError(f"unsupported AST node: {type(node).__name__}")

    # ---- name and attribute resolution ----

    def _lookup_name(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if name in self.world:
            return name  # bare entity reference
        if name in BUILTINS:
            return BUILTINS[name]
        raise EvalError(f"undefined name: {name!r}")

    def _lookup_attribute(self, node):
        # Walk down nested Attribute nodes to recover (base, [attr...])
        path = []
        cur = node
        while isinstance(cur, ast.Attribute):
            path.append(cur.attr)
            cur = cur.value
        path.reverse()
        if not isinstance(cur, ast.Name):
            base = self._visit(cur)
            for attr in path:
                if isinstance(base, dict) and attr in base:
                    base = base[attr]
                else:
                    raise EvalError(f"attribute not found in expression: .{attr}")
            return base
        base_name = cur.id
        # Resolve base: binding or direct world entity
        if base_name in self.bindings:
            entity = self.bindings[base_name]
            if not (isinstance(entity, str) and entity in self.world):
                # binding holds a non-entity value; treat as plain dict access
                value = entity
                for attr in path:
                    if isinstance(value, dict) and attr in value:
                        value = value[attr]
                    else:
                        raise EvalError(
                            f"attribute not found on binding {base_name}: .{attr}"
                        )
                return value
            entity_name = entity
        elif base_name in self.world:
            entity_name = base_name
        else:
            raise EvalError(f"undefined name in attribute access: {base_name!r}")

        value = self.world[entity_name]
        for attr in path:
            if not isinstance(value, dict) or attr not in value:
                raise EvalError(
                    f"attribute not found: {entity_name}.{'.'.join(path)}"
                )
            value = value[attr]
        self._record_attr(entity_name, path)
        return value

    def _record_attr(self, entity, attr_path):
        # Most specific match first, falling back to entity-level
        for length in range(len(attr_path), -1, -1):
            key = (entity,) + tuple(attr_path[:length])
            if key in self.attr_prov:
                self.accessed_steps.add(self.attr_prov[key])
                return

    # ---- function and predicate calls ----

    def _call(self, node):
        if not isinstance(node.func, ast.Name):
            raise EvalError("only direct function calls supported")
        fname = node.func.id
        if fname in self._predicate_names:
            args = tuple(self._eval_predicate_arg(a) for a in node.args)
            key = (fname, args)
            if key in self.predicates:
                self.accessed_steps.add(self.predicates[key]["step_id"])
                return True
            return False
        if fname in BUILTINS:
            args = [self._visit(a) for a in node.args]
            return BUILTINS[fname](*args)
        raise EvalError(f"unknown function: {fname!r}")

    def _eval_predicate_arg(self, node):
        # Predicate args are entity names — resolve bindings, otherwise use as-is.
        if isinstance(node, ast.Name):
            if node.id in self.bindings:
                return self.bindings[node.id]
            return node.id  # bare identifier = entity reference
        return self._visit(node)


# --- World construction ---

def deep_merge_facts(world, attr_prov, facts, step_id, prefix=()):
    """Merge nested facts dict into the world, recording provenance for each leaf."""
    if not isinstance(facts, dict):
        raise ValueError(f"facts must be a mapping, got {type(facts).__name__}")
    for key, value in facts.items():
        # Allow dotted keys: "user.cuisine" → ("user", "cuisine")
        parts = tuple(key.split(".")) if "." in key else (key,)
        path = prefix + parts
        if isinstance(value, dict):
            cur = world
            for p in path:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            deep_merge_facts(world, attr_prov, value, step_id, path)
            attr_prov[path] = step_id
        else:
            cur = world
            for p in path[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[path[-1]] = value
            attr_prov[path] = step_id


# --- Rule head parsing and conclusion matching ---

def parse_predicate_form(s):
    """Parse 'name(arg1, arg2, ...)' → ('name', ('arg1','arg2',...))."""
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"bad predicate form {s!r}: {e}")
    if not isinstance(tree.body, ast.Call) or not isinstance(tree.body.func, ast.Name):
        raise ValueError(f"not a predicate call: {s!r}")
    name = tree.body.func.id
    args = []
    for a in tree.body.args:
        if isinstance(a, ast.Name):
            args.append(a.id)
        elif isinstance(a, ast.Constant):
            args.append(a.value)
        else:
            raise ValueError(f"unsupported predicate arg in {s!r}")
    return name, tuple(args)


def match_conclusion_to_head(conclusion_str, head_str):
    """Bind the rule head's variables to the conclusion's ground args.
    Returns a dict {var: ground} or raises if shapes mismatch.
    """
    c_name, c_args = parse_predicate_form(conclusion_str)
    h_name, h_args = parse_predicate_form(head_str)
    if c_name != h_name:
        raise ValueError(f"predicate name mismatch: conclusion {c_name!r} vs head {h_name!r}")
    if len(c_args) != len(h_args):
        raise ValueError(f"arity mismatch: conclusion {len(c_args)} vs head {len(h_args)}")
    return {h: c for h, c in zip(h_args, c_args)}


# --- Confidence combination ---

def combine_confidences(premise_confs, rule_conf, strategy):
    if strategy == "product":
        result = rule_conf
        for c in premise_confs:
            result *= c
        return result
    if strategy == "min":
        return min(*premise_confs, rule_conf)
    raise ValueError(f"unknown combine strategy: {strategy!r}")


# --- Main verification pipeline ---

def verify(trace_steps, tolerance=DEFAULT_TOLERANCE):
    report = Report()
    report.n_steps = len(trace_steps)

    # Pass 1: structural validation, build steps_by_id
    steps_by_id = {}
    for i, step in enumerate(trace_steps):
        if not isinstance(step, dict):
            report.add(Issue(f"#{i}", "error", "step must be a YAML mapping"))
            continue
        kind = step.get("kind")
        sid = step.get("id", f"#{i}")
        if kind not in KIND_FIELDS:
            report.add(Issue(sid, "error", f"unknown kind: {kind!r}"))
            continue
        spec = KIND_FIELDS[kind]
        for f in spec["required"]:
            if f not in step:
                report.add(Issue(sid, "error", f"missing required field: {f}"))
        allowed = spec["required"] | spec["optional"]
        for f in step:
            if f not in allowed:
                report.add(Issue(sid, "warning", f"unknown field: {f}"))
        if sid in steps_by_id:
            report.add(Issue(sid, "error", "duplicate id"))
        else:
            steps_by_id[sid] = step

    if not report.ok():
        return report

    # Pass 2: walk in order, build world and predicates, verify each step
    world = {}
    attr_prov = {}
    predicates = {}     # (pred_name, args_tuple) -> {step_id, conf}

    for step in trace_steps:
        sid = step["id"]
        kind = step["kind"]

        if kind == "observe":
            report.n_observe += 1
            try:
                deep_merge_facts(world, attr_prov, step["facts"], sid)
            except Exception as e:
                report.add(Issue(sid, "error", f"facts ill-formed: {e}"))

        elif kind == "rule":
            report.n_rule += 1
            try:
                parse_predicate_form(step["head"])
                ast.parse(step["body"], mode="eval")
            except (ValueError, SyntaxError) as e:
                report.add(Issue(sid, "error", f"rule ill-formed: {e}"))
            combine = step.get("combine", DEFAULT_COMBINE)
            if combine not in VALID_COMBINE:
                report.add(Issue(sid, "error", f"unknown combine: {combine!r}"))
            if not (0 <= step["conf"] <= 1):
                report.add(Issue(sid, "error", f"conf out of range: {step['conf']}"))

        elif kind == "infer":
            verify_infer(step, steps_by_id, world, attr_prov, predicates, report, tolerance)
            if any(i.step_id == sid and i.severity == "error" for i in report.issues):
                continue
            # Register the derived predicate fact
            try:
                pred_name, pred_args = parse_predicate_form(step["conclusion"])
                predicates[(pred_name, pred_args)] = {"step_id": sid, "conf": step["conf"]}
            except ValueError:
                pass

        elif kind == "consider":
            verify_consider(step, steps_by_id, world, attr_prov, predicates, report)

        elif kind == "decide":
            verify_decide(step, steps_by_id, report)

    return report


def verify_infer(step, steps_by_id, world, attr_prov, predicates, report, tolerance):
    sid = step["id"]
    report.n_infer_checked += 1

    rule_id = step["via"]
    if rule_id not in steps_by_id or steps_by_id[rule_id]["kind"] != "rule":
        report.add(Issue(sid, "error", f"via={rule_id!r} is not a rule"))
        return
    rule = steps_by_id[rule_id]

    from_ids = step["from"]
    if not isinstance(from_ids, list):
        report.add(Issue(sid, "error", "from must be a list"))
        return
    for fid in from_ids:
        if fid not in steps_by_id:
            report.add(Issue(sid, "error", f"from references unknown step: {fid!r}"))
            return

    # 1. Match conclusion to head, recover binding
    try:
        binding = match_conclusion_to_head(step["conclusion"], rule["head"])
    except ValueError as e:
        report.add(Issue(sid, "error", f"conclusion does not match rule head: {e}"))
        return

    # 2. Evaluate the rule body in the current world with binding
    evaluator = WorldEvaluator(world, attr_prov, predicates, binding)
    try:
        body_result = evaluator.eval(rule["body"])
    except EvalError as e:
        report.add(Issue(sid, "error", f"body evaluation failed: {e}"))
        return

    # 3. Body must evaluate to truthy
    if not body_result:
        report.add(Issue(sid, "error",
            f"rule body did not fire for binding {binding}; "
            f"derivation invalid"))
        return

    # 4. Verify all accessed steps were cited
    cited = set(from_ids)
    used = evaluator.accessed_steps
    uncited = used - cited
    if uncited:
        report.add(Issue(sid, "error",
            f"derivation used premises not in `from`: {sorted(uncited)} "
            f"(cited: {sorted(cited)})"))

    # 5. Check confidence consistency
    combine = rule.get("combine", DEFAULT_COMBINE)
    premise_confs = []
    for fid in from_ids:
        prem = steps_by_id[fid]
        if "conf" not in prem:
            report.add(Issue(sid, "warning",
                f"premise {fid} has no conf; treating as 1.0"))
            premise_confs.append(1.0)
        else:
            premise_confs.append(prem["conf"])
    expected = combine_confidences(premise_confs, rule["conf"], combine)
    stated = step["conf"]
    if abs(expected - stated) > tolerance:
        report.add(Issue(sid, "error",
            f"conf mismatch: stated {stated:.4f}, expected {expected:.4f} "
            f"under combine={combine} (tolerance ±{tolerance})"))


def verify_consider(step, steps_by_id, world, attr_prov, predicates, report):
    sid = step["id"]
    report.n_consider_checked += 1

    rule_id = step["rejected_by"]
    if rule_id not in steps_by_id or steps_by_id[rule_id]["kind"] != "rule":
        report.add(Issue(sid, "error", f"rejected_by={rule_id!r} is not a rule"))
        return
    rule = steps_by_id[rule_id]

    candidate = step["candidate"]
    if not isinstance(candidate, str) or candidate not in world:
        report.add(Issue(sid, "error", f"candidate {candidate!r} not in world"))
        return

    # Recover the rule's variable name and bind to the candidate
    try:
        _, head_args = parse_predicate_form(rule["head"])
    except ValueError as e:
        report.add(Issue(sid, "error", f"rule head ill-formed: {e}"))
        return
    if len(head_args) != 1:
        report.add(Issue(sid, "warning",
            f"consider supports unary rules in v1; rule has arity {len(head_args)}"))
        return
    binding = {head_args[0]: candidate}

    evaluator = WorldEvaluator(world, attr_prov, predicates, binding)
    try:
        body_result = evaluator.eval(rule["body"])
    except EvalError as e:
        report.add(Issue(sid, "error", f"body evaluation failed: {e}"))
        return
    if body_result:
        report.add(Issue(sid, "error",
            f"rejection invalid: rule {rule_id} actually fires for {candidate!r}"))


def verify_decide(step, steps_by_id, report):
    sid = step["id"]
    report.n_decide_checked += 1

    from_ids = step["from"]
    if not isinstance(from_ids, list):
        report.add(Issue(sid, "error", "from must be a list"))
        return
    premise_confs = []
    for fid in from_ids:
        if fid not in steps_by_id:
            report.add(Issue(sid, "error", f"from references unknown step: {fid!r}"))
            continue
        prem = steps_by_id[fid]
        if "conf" in prem:
            premise_confs.append(prem["conf"])

    stated = step["conf"]
    if not (0 <= stated <= 1):
        report.add(Issue(sid, "error", f"conf out of range: {stated}"))
        return
    if premise_confs and stated > min(premise_confs) + DEFAULT_TOLERANCE:
        report.add(Issue(sid, "warning",
            f"decision conf {stated:.4f} exceeds min premise conf "
            f"{min(premise_confs):.4f}; suspicious"))


# --- CLI ---

def main():
    if len(sys.argv) != 2:
        print("usage: verifier.py <trace.yaml>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1])
    with open(path) as f:
        trace = yaml.safe_load(f)
    if not isinstance(trace, list):
        print(f"error: trace must be a YAML list of step mappings", file=sys.stderr)
        sys.exit(2)

    report = verify(trace)

    print(f"Trace: {path}")
    print(f"  steps: {report.n_steps}")
    print(f"    observe: {report.n_observe}")
    print(f"    rule:    {report.n_rule}")
    print(f"    infer (checked):    {report.n_infer_checked}")
    print(f"    consider (checked): {report.n_consider_checked}")
    print(f"    decide (checked):   {report.n_decide_checked}")
    if report.issues:
        print(f"\nIssues ({len(report.errors())} errors, {len(report.warnings())} warnings):")
        for issue in report.issues:
            print(issue)
    else:
        print("\n  no issues found.")
    sys.exit(0 if report.ok() else 1)


if __name__ == "__main__":
    main()
