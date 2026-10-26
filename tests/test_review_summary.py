"""Usage accounting must not hide failures or invent remaining allowance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_summary import render, summarize


def record(status="review_received", usage=None, round_number=1, attempts=1):
    return {"model": "review-model", "provider": "cloud", "round": round_number,
            "status": status, "inference_attempts": attempts,
            "actual_identity": {"provider_reported_model": "review-model", "usage": usage}}


class SummaryTests(unittest.TestCase):
    def test_invalid_response_still_consumes_reported_tokens(self):
        result = {"reviews": [record(usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}),
                  record("unstructured_response", {"input_tokens": 150, "output_tokens": 50, "total_tokens": 200}, 2)]}
        original = deepcopy(result)
        summary = summarize(result)
        self.assertEqual(result, original)
        self.assertEqual(summary["tokens"]["known"], {"input_tokens": 250, "output_tokens": 70, "total_tokens": 320})
        self.assertTrue(summary["tokens"]["complete"])
        self.assertEqual(summary["inference_attempts"], 2)
        self.assertEqual(summary["completed_reviews"], 1)
        self.assertEqual(summary["models"][0]["rounds"][1]["status"], "unstructured_response")

    def test_missing_usage_is_partial_not_zero_and_skips_are_not_charged(self):
        summary = summarize({"reviews": [record(usage={"total_tokens": 10}), record("timeout", round_number=2),
                           record("auth_missing", attempts=0)]})
        self.assertEqual(summary["tokens"]["known"]["total_tokens"], 10)
        self.assertEqual(summary["tokens"]["missing_attempts"]["total_tokens"], 1)
        self.assertEqual(summary["tokens"]["missing_attempts"]["input_tokens"], 2)
        self.assertFalse(summary["tokens"]["complete"])
        self.assertIn("10+", render(summary))
        self.assertEqual(summary["models"][0]["remaining_quota"]["status"], "unavailable")
        self.assertEqual(summary["codex_remaining"]["status"], "requires_live_usage_tool")

    def test_single_result_keeps_mismatch_and_unverified_identity_visible(self):
        summary = summarize({"requested": {"model": "chosen", "provider": "cloud"},
            "status": "identity_unverified", "inference_attempts": 1,
            "pal_metadata": {"provider_reported_model": "different", "usage": {"total_tokens": 0}}})
        model = summary["models"][0]
        self.assertEqual(model["requested_model"], "chosen")
        self.assertEqual(model["provider_reported_models"], ["different"])
        self.assertEqual(summary["completed_reviews"], 0)
        self.assertEqual(model["tokens"]["missing_attempts"]["total_tokens"], 0)
        self.assertIn("identity_unverified", render(summary))

    def test_invalid_counts_are_unknown_and_model_names_cannot_break_table(self):
        item = record(usage={"input_tokens": -1, "output_tokens": True, "total_tokens": "40"})
        item["model"] = "model|with\nnewline"
        item["actual_identity"]["provider_reported_model"] = None
        summary = summarize({"reviews": [item]})
        self.assertEqual(summary["tokens"]["missing_attempts"], dict.fromkeys(("input_tokens", "output_tokens", "total_tokens"), 1))
        self.assertEqual(summary["models"][0]["identity_missing_records"], 1)
        self.assertIn("model\\|with newline", render(summary))


if __name__ == "__main__":
    unittest.main()
