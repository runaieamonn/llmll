"""Tests for the llmll v1 verifier."""

import copy
import os
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import verify, parse_predicate_form, match_conclusion_to_head, combine_confidences


EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "restaurant_recommendation.yaml"


def load_example():
    with open(EXAMPLE_PATH) as f:
        return yaml.safe_load(f)


class TestPredicateParsing(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_predicate_form("foo(x)"), ("foo", ("x",)))

    def test_multi_arg(self):
        self.assertEqual(parse_predicate_form("p(a, b, c)"), ("p", ("a", "b", "c")))

    def test_match_head(self):
        self.assertEqual(
            match_conclusion_to_head("cuisine_match(r1)", "cuisine_match(R)"),
            {"R": "r1"},
        )

    def test_match_arity_mismatch(self):
        with self.assertRaises(ValueError):
            match_conclusion_to_head("p(a, b)", "p(X)")


class TestCombine(unittest.TestCase):
    def test_product(self):
        self.assertAlmostEqual(combine_confidences([0.8, 0.9], 0.95, "product"), 0.684)

    def test_min(self):
        self.assertAlmostEqual(combine_confidences([0.8, 0.9], 0.95, "min"), 0.8)


class TestGoodTrace(unittest.TestCase):
    def test_example_passes(self):
        trace = load_example()
        report = verify(trace)
        self.assertTrue(
            report.ok(),
            f"example should pass; errors: {report.errors()}",
        )
        self.assertGreater(report.n_infer_checked, 0)
        self.assertGreater(report.n_consider_checked, 0)
        self.assertEqual(report.n_decide_checked, 1)


class TestAdversarialCases(unittest.TestCase):
    """Each test tampers with the good trace in one specific way and
    verifies the verifier catches it."""

    def setUp(self):
        self.good = load_example()

    def _tamper(self, fn):
        trace = copy.deepcopy(self.good)
        fn(trace)
        return verify(trace)

    def _step(self, trace, sid):
        return next(s for s in trace if s.get("id") == sid)

    def test_tampered_confidence_too_high(self):
        report = self._tamper(
            lambda t: self._step(t, "i_r1_cuisine").update({"conf": 0.99})
        )
        self.assertFalse(report.ok())
        self.assertTrue(any("conf mismatch" in i.message for i in report.errors()))

    def test_tampered_confidence_too_low(self):
        report = self._tamper(
            lambda t: self._step(t, "i_r1_cuisine").update({"conf": 0.10})
        )
        self.assertFalse(report.ok())
        self.assertTrue(any("conf mismatch" in i.message for i in report.errors()))

    def test_uncited_premise(self):
        # Remove o_user from i_r1_cuisine.from — but the body still references user.cuisine
        report = self._tamper(
            lambda t: self._step(t, "i_r1_cuisine").update({"from": ["o_r1"]})
        )
        self.assertFalse(report.ok())
        self.assertTrue(any("not in `from`" in i.message for i in report.errors()))

    def test_wrong_rule_applied(self):
        # Claim cuisine_match(r1) was derived via r_budget — head names won't match
        report = self._tamper(
            lambda t: self._step(t, "i_r1_cuisine").update({"via": "r_budget"})
        )
        self.assertFalse(report.ok())
        self.assertTrue(any("does not match rule head" in i.message for i in report.errors()))

    def test_rule_body_does_not_fire(self):
        # Move r1's cuisine away from italian — the rule body for cuisine_match(r1) will be false
        def tamper(t):
            self._step(t, "o_r1")["facts"]["r1"]["cuisine"] = "thai"
        report = self._tamper(tamper)
        self.assertFalse(report.ok())
        self.assertTrue(any("did not fire" in i.message for i in report.errors()))

    def test_invalid_rejection(self):
        # Reject r1 by r_cuisine, but r1 actually IS italian — rule fires → rejection invalid
        def tamper(t):
            t.append({
                "id": "c_bad",
                "kind": "consider",
                "candidate": "r1",
                "rejected_by": "r_cuisine",
                "reason": "fake rejection",
            })
        report = self._tamper(tamper)
        self.assertFalse(report.ok())
        self.assertTrue(any(
            "rejection invalid" in i.message and i.step_id == "c_bad"
            for i in report.errors()
        ))

    def test_unknown_step_reference(self):
        report = self._tamper(
            lambda t: self._step(t, "i_r1_cuisine").update({"from": ["o_nonexistent"]})
        )
        self.assertFalse(report.ok())
        self.assertTrue(any("unknown step" in i.message for i in report.errors()))

    def test_unknown_via_rule(self):
        report = self._tamper(
            lambda t: self._step(t, "i_r1_cuisine").update({"via": "r_nope"})
        )
        self.assertFalse(report.ok())
        self.assertTrue(any("not a rule" in i.message for i in report.errors()))

    def test_duplicate_id(self):
        def tamper(t):
            t.append(copy.deepcopy(self._step(t, "o_r1")))
        report = self._tamper(tamper)
        self.assertFalse(report.ok())
        self.assertTrue(any("duplicate id" in i.message for i in report.errors()))

    def test_missing_required_field(self):
        def tamper(t):
            del self._step(t, "i_r1_cuisine")["via"]
        report = self._tamper(tamper)
        self.assertFalse(report.ok())
        self.assertTrue(any("missing required field" in i.message for i in report.errors()))

    def test_unknown_kind(self):
        def tamper(t):
            t.append({"id": "weird", "kind": "speculate", "what": "wild guess"})
        report = self._tamper(tamper)
        self.assertFalse(report.ok())
        self.assertTrue(any("unknown kind" in i.message for i in report.errors()))

    def test_decision_conf_too_high(self):
        # Decision confidence exceeds min premise conf — warning
        def tamper(t):
            self._step(t, "d_recommend")["conf"] = 0.99
        report = self._tamper(tamper)
        # This is a warning, not error, so trace still ok
        self.assertTrue(any(
            "exceeds min premise conf" in i.message for i in report.warnings()
        ))


class TestComposedInference(unittest.TestCase):
    """Specifically test that compositional inferences (e.g., good_match)
    correctly chain through cited prior inferences."""

    def setUp(self):
        self.good = load_example()

    def test_compositional_premise_check(self):
        # i_r1_good cites i_r1_cuisine; if we drop one, it should fail
        trace = copy.deepcopy(self.good)
        good_step = next(s for s in trace if s["id"] == "i_r1_good")
        good_step["from"] = ["i_r1_budget", "i_r1_nearby", "i_r1_open"]  # dropped i_r1_cuisine
        report = verify(trace)
        self.assertFalse(report.ok())
        self.assertTrue(any(
            "not in `from`" in i.message and i.step_id == "i_r1_good"
            for i in report.errors()
        ))


if __name__ == "__main__":
    unittest.main()
