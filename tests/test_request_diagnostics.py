import json
import tempfile
import unittest
from pathlib import Path

from miser.ledger import Ledger, receipt, request_diagnostics


class RequestDiagnosticsTests(unittest.TestCase):
    def test_breakdown_contains_sizes_not_prompt_content(self):
        messages = [{"role": "system", "content": "private instruction"},
                    {"role": "user", "content": "private task"},
                    {"role": "tool", "content": "private source"}]
        result = request_diagnostics(messages, [{"name": "private_tool"}])
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(result["message_count"], 3)
        self.assertEqual(result["tool_count"], 1)
        self.assertGreater(result["component_tokens_estimate"]["history"], 0)

    def test_diagnostics_never_inflate_provider_bill(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(Path(root) / "ledger.json")
            for _ in range(2):
                ledger.record("model_request", **request_diagnostics(
                    [{"role": "system", "content": "x" * 10000}], []))
            ledger.model({"usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                    "total_tokens": 15}}, 0.1)
            result = receipt(ledger.data)
            self.assertEqual(result["total_tokens"], 15)
            self.assertEqual(result["measured_request_count"], 2)
            self.assertGreater(result["request_component_tokens_estimate"]["instructions"], 4000)

    def test_older_receipts_remain_readable(self):
        result = receipt({"events": [], "status": "incomplete"})
        self.assertEqual(result["measured_request_count"], 0)
