"""Tests for the llmll interpreter."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llmll import run, reset_global, LlmllError


class TestLiterals(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_null(self):
        self.assertIsNone(run(None))

    def test_bool(self):
        self.assertIs(run(True), True)
        self.assertIs(run(False), False)

    def test_number(self):
        self.assertEqual(run(42), 42)
        self.assertEqual(run(3.14), 3.14)

    def test_string(self):
        self.assertEqual(run("hello"), "hello")

    def test_empty_array_is_literal(self):
        self.assertEqual(run([]), [])

    def test_array_with_non_string_first(self):
        self.assertEqual(run([1, 2, 3]), [1, 2, 3])

    def test_nested_literal_array_not_evaluated(self):
        self.assertEqual(run([1, "$x", 3]), [1, "$x", 3])

    def test_object(self):
        self.assertEqual(run({"a": 1}), {"a": 1})


class TestVariables(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_unbound_raises(self):
        with self.assertRaises(LlmllError):
            run("$nope")

    def test_global_lookup(self):
        prog = ["do", ["def", "x", 5], "$x"]
        self.assertEqual(run(prog), 5)

    def test_let_binds(self):
        self.assertEqual(run(["let", [["x", 5]], "$x"]), 5)

    def test_let_sequential(self):
        self.assertEqual(
            run(["let", [["x", 5], ["y", ["add", "$x", 1]]], "$y"]),
            6,
        )


class TestArithmetic(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_add(self):
        self.assertEqual(run(["add", 1, 2, 3]), 6)
        self.assertEqual(run(["add"]), 0)

    def test_sub(self):
        self.assertEqual(run(["sub", 10, 3]), 7)

    def test_mul(self):
        self.assertEqual(run(["mul", 2, 3, 4]), 24)
        self.assertEqual(run(["mul"]), 1)

    def test_div(self):
        self.assertEqual(run(["div", 10, 2]), 5)

    def test_div_zero(self):
        with self.assertRaises(LlmllError):
            run(["div", 1, 0])

    def test_mod(self):
        self.assertEqual(run(["mod", 10, 3]), 1)

    def test_neg(self):
        self.assertEqual(run(["neg", 5]), -5)

    def test_type_error(self):
        with self.assertRaises(LlmllError):
            run(["add", 1, "two"])


class TestComparison(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_eq(self):
        self.assertTrue(run(["eq", 1, 1]))
        self.assertFalse(run(["eq", 1, 2]))
        self.assertTrue(run(["eq", [1, 2], [1, 2]]))

    def test_ordering(self):
        self.assertTrue(run(["lt", 1, 2]))
        self.assertTrue(run(["gt", 3, 2]))
        self.assertTrue(run(["le", 2, 2]))
        self.assertTrue(run(["ge", 2, 2]))


class TestBoolean(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_and_short_circuit(self):
        self.assertEqual(run(["and", True, True, 5]), 5)
        self.assertIs(run(["and", True, False, 5]), False)

    def test_or_short_circuit(self):
        self.assertEqual(run(["or", False, 0, 5]), 5)
        self.assertEqual(run(["or", False, None, 0]), 0)

    def test_not(self):
        self.assertIs(run(["not", False]), True)
        self.assertIs(run(["not", 0]), True)
        self.assertIs(run(["not", 1]), False)


class TestControl(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_if_true(self):
        self.assertEqual(run(["if", True, "yes", "no"]), "yes")

    def test_if_false(self):
        self.assertEqual(run(["if", False, "yes", "no"]), "no")

    def test_if_lazy(self):
        # else branch would error if evaluated
        self.assertEqual(run(["if", True, 1, ["div", 1, 0]]), 1)

    def test_do_returns_last(self):
        self.assertEqual(run(["do", 1, 2, 3]), 3)


class TestFunctions(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_lambda_call(self):
        prog = ["call", ["lambda", ["x"], ["add", "$x", 1]], 5]
        self.assertEqual(run(prog), 6)

    def test_closure_captures(self):
        prog = ["let", [["y", 10]],
                ["call", ["lambda", ["x"], ["add", "$x", "$y"]], 5]]
        self.assertEqual(run(prog), 15)

    def test_closure_is_inspectable_json(self):
        prog = ["lambda", ["x"], "$x"]
        result = run(prog)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "closure")
        # round-trip through JSON
        json.dumps(result)

    def test_recursive_def(self):
        prog = ["do",
                ["def", "fact", ["lambda", ["n"],
                    ["if", ["le", "$n", 1], 1,
                        ["mul", "$n", ["call", "$fact", ["sub", "$n", 1]]]]]],
                ["call", "$fact", 5]]
        self.assertEqual(run(prog), 120)


class TestErrors(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_try_catches(self):
        result = run(["try", ["div", 1, 0]])
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "error")

    def test_try_passes(self):
        self.assertEqual(run(["try", ["add", 1, 2]]), 3)

    def test_try_unbound_var(self):
        result = run(["try", "$nope"])
        self.assertEqual(result[0], "error")

    def test_unknown_op(self):
        with self.assertRaises(LlmllError):
            run(["floob", 1])


class TestLists(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_list_construct(self):
        self.assertEqual(run(["list", 1, 2, 3]), [1, 2, 3])

    def test_list_with_computed(self):
        prog = ["let", [["x", 5]], ["list", 1, "$x", 3]]
        self.assertEqual(run(prog), [1, 5, 3])

    def test_len(self):
        self.assertEqual(run(["len", [1, 2, 3]]), 3)
        self.assertEqual(run(["len", "abc"]), 3)
        self.assertEqual(run(["len", {"a": 1}]), 1)

    def test_get(self):
        self.assertEqual(run(["get", [10, 20, 30], 1]), 20)
        self.assertEqual(run(["get", {"x": 5}, "x"]), 5)
        self.assertEqual(run(["get", "abc", 1]), "b")

    def test_get_out_of_range(self):
        with self.assertRaises(LlmllError):
            run(["get", [1, 2], 10])

    def test_append(self):
        self.assertEqual(run(["append", [1, 2], 3]), [1, 2, 3])

    def test_concat_lists(self):
        self.assertEqual(run(["concat", [1, 2], [3, 4]]), [1, 2, 3, 4])

    def test_concat_strings(self):
        self.assertEqual(run(["concat", "foo", "bar"]), "foobar")

    def test_slice(self):
        self.assertEqual(run(["slice", [1, 2, 3, 4], 1, 3]), [2, 3])
        self.assertEqual(run(["slice", "abcdef", 1, 4]), "bcd")

    def test_range(self):
        self.assertEqual(run(["range", 0, 5]), [0, 1, 2, 3, 4])

    def test_map(self):
        prog = ["map", ["lambda", ["x"], ["mul", "$x", 2]], [1, 2, 3]]
        self.assertEqual(run(prog), [2, 4, 6])

    def test_filter(self):
        prog = ["filter", ["lambda", ["x"], ["gt", "$x", 2]], [1, 2, 3, 4]]
        self.assertEqual(run(prog), [3, 4])

    def test_reduce(self):
        prog = ["reduce",
                ["lambda", ["a", "b"], ["add", "$a", "$b"]],
                0, [1, 2, 3, 4]]
        self.assertEqual(run(prog), 10)


class TestDicts(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_dict_construct(self):
        self.assertEqual(run(["dict", "a", 1, "b", 2]), {"a": 1, "b": 2})

    def test_keys_vals(self):
        self.assertEqual(set(run(["keys", {"a": 1, "b": 2}])), {"a", "b"})
        self.assertEqual(set(run(["vals", {"a": 1, "b": 2}])), {1, 2})

    def test_has(self):
        self.assertTrue(run(["has", {"a": 1}, "a"]))
        self.assertFalse(run(["has", {"a": 1}, "z"]))

    def test_put_is_pure(self):
        prog = ["let", [["d", {"a": 1}]],
                ["list", ["put", "$d", "b", 2], "$d"]]
        self.assertEqual(run(prog), [{"a": 1, "b": 2}, {"a": 1}])


class TestStrings(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_str_concat(self):
        self.assertEqual(run(["str", "hello ", "world"]), "hello world")

    def test_str_convert(self):
        self.assertEqual(run(["str", "n=", 42]), "n=42")

    def test_split(self):
        self.assertEqual(run(["split", "a,b,c", ","]), ["a", "b", "c"])

    def test_join(self):
        # ["a","b","c"] would be parsed as a call (first elem is a string),
        # so to pass a literal list of strings we go through the `list` constructor.
        self.assertEqual(run(["join", ["list", "a", "b", "c"], "-"]), "a-b-c")


class TestType(unittest.TestCase):
    def setUp(self):
        reset_global()

    def test_type(self):
        self.assertEqual(run(["type", 1]), "num")
        self.assertEqual(run(["type", "x"]), "str")
        self.assertEqual(run(["type", True]), "bool")
        self.assertEqual(run(["type", None]), "null")
        self.assertEqual(run(["type", [1, 2, 3]]), "list")
        self.assertEqual(run(["type", {"a": 1}]), "dict")
        self.assertEqual(run(["type", ["lambda", ["x"], "$x"]]), "closure")


class TestExamples(unittest.TestCase):
    """End-to-end: each example file runs without error."""

    def setUp(self):
        reset_global()

    def _load(self, name):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "examples", name,
        )
        with open(path) as f:
            return json.load(f)

    def test_factorial(self):
        reset_global()
        # don't capture stdout — just run and check no error
        run(self._load("factorial.json"))

    def test_fib(self):
        reset_global()
        run(self._load("fib.json"))

    def test_fizzbuzz(self):
        reset_global()
        run(self._load("fizzbuzz.json"))

    def test_sum_of_squares(self):
        reset_global()
        run(self._load("sum_of_squares.json"))


if __name__ == "__main__":
    unittest.main()
