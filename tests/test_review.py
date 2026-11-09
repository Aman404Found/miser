import json
import tempfile
import unittest
from pathlib import Path

from miser.ledger import Ledger, receipt
from miser.review import review_evidence


class ReviewTests(unittest.TestCase):
    def review(self, decision, candidates=None, usage=True):
        class Client:
            def complete(self, *args, **kwargs):
                result = {"choices": [{"message": {"content": json.dumps(decision)}}]}
                if usage:
                    result["usage"] = {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
                return result
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(Path(root) / "ledger.json")
            card = {"claim": "API accepts flag", "applicable_version": "2.0", "freshness_score": None,
                    "candidates": candidates if candidates is not None else [
                        {"url": "https://docs.example.org/api", "excerpt": "Version 2.0 accepts flag."}]}
            result = review_evidence(card, Client(), ledger)
            return result, receipt(ledger.data)

    def decision(self):
        return {"verdict": "supported", "reason": "Explicitly documented.", "citations": [
            {"url": "https://docs.example.org/api", "quote": "accepts flag",
             "version_quote": "Version 2.0"}]}

    def test_anchored_verdict_records_model_spend(self):
        result, bill = self.review(self.decision())
        self.assertEqual(result["verdict"], "supported")
        self.assertEqual(bill["total_tokens"], 70)
        self.assertIsNone(result["freshness_score"])

    def test_fabricated_url_quote_or_version_abstains(self):
        for field, value in [("url", "https://evil.invalid"), ("quote", "invented"),
                             ("version_quote", "Version 3.0")]:
            with self.subTest(field=field):
                decision = self.decision()
                decision["citations"][0][field] = value
                result, _ = self.review(decision)
                self.assertEqual(result["verdict"], "insufficient_evidence")

    def test_missing_evidence_skips_paid_review(self):
        result, bill = self.review({}, candidates=[])
        self.assertEqual(result["verdict"], "insufficient_evidence")
        self.assertEqual(bill["model_calls"], 0)

    def test_missing_usage_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "usage"):
            self.review(self.decision(), usage=False)
