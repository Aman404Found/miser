import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from miser.agent import run_agent
from miser.client import (MAX_RETRY_AFTER_SECONDS, ModelClient, RemoteHTTPError,
                          _retry_after, parse_models, post_json)
from miser.ledger import Ledger, receipt
from miser.tools import ToolRunner
from miser.workspace import Workspace


def chat_response(model, content="done", usage=(10, 5)):
    return {"choices": [{"message": {"role": "assistant", "content": content}}],
            "model": model,
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                      "total_tokens": usage[0] + usage[1]}}


class ModelFallbackTests(unittest.TestCase):
    def test_parse_models_trims_and_deduplicates(self):
        self.assertEqual(parse_models("a, b ,,a,c"), ["a", "b", "c"])
        self.assertEqual(parse_models(["x", "y"]), ["x", "y"])
        self.assertEqual(parse_models(None), [])

    def test_fallback_env_configuration_excludes_primary(self):
        with patch.dict(os.environ, {"MISER_FALLBACK_MODELS": "primary,backup"}):
            client = ModelClient("primary")
        self.assertEqual(client.candidates, ["primary", "backup"])

    def test_rate_limit_falls_back_to_secondary_model(self):
        notices, bodies = [], []

        def transport(url, body, headers=None, timeout=60):
            bodies.append(body["model"])
            if body["model"] == "primary/model":
                raise RemoteHTTPError(429, "Remote service returned HTTP 429 — rate or quota limit")
            return chat_response(body["model"])

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("primary/model", fallbacks=["backup/model"],
                                 on_notice=notices.append, sleep=lambda seconds: None)
            result = client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(bodies, ["primary/model", "backup/model"])
        self.assertEqual(result["model"], "backup/model")
        self.assertIn("429", notices[0])
        self.assertIn("backup/model", notices[0])
        event = client.consume_fallback()
        self.assertEqual(event, {"from_model": "primary/model", "to_model": "backup/model",
                                 "status": 429})
        self.assertIsNone(client.consume_fallback())

    def test_unavailable_provider_falls_back_and_records_status(self):
        def transport(url, body, headers=None, timeout=60):
            if body["model"] == "primary/model":
                raise RemoteHTTPError(503, "unavailable")
            return chat_response(body["model"])

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("primary/model", fallbacks="backup/model",
                                 sleep=lambda seconds: None)
            client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(client.consume_fallback()["status"], 503)

    def test_auth_error_does_not_fall_back(self):
        calls = []

        def transport(url, body, headers=None, timeout=60):
            calls.append(body["model"])
            raise RemoteHTTPError(401, "Remote service returned HTTP 401 — authentication rejected")

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("primary/model", fallbacks=["backup/model"],
                                 sleep=lambda seconds: None)
            with self.assertRaisesRegex(RuntimeError, "401"):
                client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(calls, ["primary/model"])

    def test_chain_is_exhausted_with_a_useful_error(self):
        def transport(url, body, headers=None, timeout=60):
            raise RemoteHTTPError(429, "Remote service returned HTTP 429 — rate or quota limit")

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("a", fallbacks=["b", "c"],
                                 sleep=lambda seconds: None)
            with self.assertRaisesRegex(RuntimeError, "429"):
                client.complete([{"role": "user", "content": "hi"}], [])


class RetryTests(unittest.TestCase):
    def test_transient_unavailable_is_retried_then_succeeds(self):
        calls, sleeps = [], []

        def transport(url, body, headers=None, timeout=60):
            calls.append(body["model"])
            if len(calls) == 1:
                raise RemoteHTTPError(503, "unavailable")
            return chat_response(body["model"])

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("only/model", sleep=sleeps.append)
            result = client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(calls, ["only/model", "only/model"])
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(result["model"], "only/model")

    def test_persistent_unavailable_stops_after_max_attempts(self):
        calls, sleeps = [], []

        def transport(url, body, headers=None, timeout=60):
            calls.append(body["model"])
            raise RemoteHTTPError(503, "unavailable")

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("only/model", sleep=sleeps.append)
            with self.assertRaises(RemoteHTTPError) as caught:
                client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(len(calls), ModelClient.MAX_ATTEMPTS)
        self.assertEqual(sleeps, [2.0, 5.0])
        self.assertEqual(caught.exception.status, 503)

    def test_retry_after_header_sets_the_delay(self):
        sleeps = []

        def transport(url, body, headers=None, timeout=60):
            raise RemoteHTTPError(429, "slow down", retry_after=7.0)

        with patch("miser.client.post_json", side_effect=transport):
            client = ModelClient("only/model", sleep=sleeps.append)
            with self.assertRaises(RemoteHTTPError):
                client.complete([{"role": "user", "content": "hi"}], [])
        self.assertEqual(sleeps, [7.0, 7.0])

    def test_retry_after_parsing(self):
        message = Message()
        message["Retry-After"] = "7"
        self.assertEqual(_retry_after(message), 7.0)
        self.assertIsNone(_retry_after(None))
        self.assertIsNone(_retry_after(Message()))

        message = Message()
        message["Retry-After"] = "9999"
        self.assertEqual(_retry_after(message), MAX_RETRY_AFTER_SECONDS)

        message = Message()
        message["Retry-After"] = "Wed, 21 Oct 2015 07:28:00 GMT"
        self.assertIsNone(_retry_after(message))

    def test_http_error_keeps_retry_after_from_the_response(self):
        headers = Message()
        headers["Retry-After"] = "7"
        error = urllib.error.HTTPError("http://gateway", 429, "Too Many Requests", headers, None)
        with patch("miser.client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RemoteHTTPError) as caught:
                post_json("http://gateway/chat/completions", {})
        self.assertEqual(caught.exception.retry_after, 7.0)


class ModelUnavailableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        shutil.copytree(Path(__file__).resolve().parent.parent / "examples" / "python_bug",
                        self.repo)
        self.ledger = Ledger(self.root / "ledger.json", mode="unit-test-fixture")
        self.workspace = Workspace(self.repo)
        self.runner = ToolRunner(self.workspace, self.ledger,
                                 [sys.executable, "-m", "unittest", "discover", "-s", "."])

    def test_provider_outage_ends_with_one_model_unavailable_status(self):
        class Unavailable:
            def complete(self, messages, tools, max_tokens=1024, **kwargs):
                raise RemoteHTTPError(503, "Remote service returned HTTP 503 — provider unavailable")

        status = run_agent("Fix the discount calculation", Unavailable(), self.runner,
                           self.ledger, max_steps=1)

        self.assertEqual(status, "model_unavailable")
        self.assertEqual(self.ledger.data["status"], "model_unavailable")
        bill = receipt(self.ledger.data)
        self.assertEqual(bill["failed_model_requests"], 1)
        self.assertFalse(bill["usage_complete"])


class ArchitectEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        shutil.copytree(Path(__file__).resolve().parent.parent / "examples" / "python_bug",
                        self.repo)
        self.ledger = Ledger(self.root / "ledger.json", mode="unit-test-fixture")
        self.workspace = Workspace(self.repo)
        self.runner = ToolRunner(self.workspace, self.ledger,
                                 [sys.executable, "-m", "unittest", "discover", "-s", "."])

    def test_architect_plans_then_editor_edits(self):
        class Architect:
            def __init__(self):
                self.calls = 0

            def complete(self, messages, tools, max_tokens=1024, **kwargs):
                self.calls += 1
                self.tools = tools
                return chat_response("architect/model", "1. Zoom pricing.py\n2. Fix the discount formula")

        class Editor:
            def __init__(self, tool_runner):
                self.state = None
                self.calls = 0
                self.tool_runner = tool_runner

            def complete(self, messages, tools, max_tokens=1024, **kwargs):
                self.calls += 1
                self.state = json.loads(messages[1]["content"])
                if self.calls == 1:
                    version = json.loads(
                        self.tool_runner.invoke("zoom", {"path": "pricing.py", "level": 2}))["version"]
                    call = {"id": "edit-1", "type": "function",
                            "function": {"name": "edit", "arguments": json.dumps({
                                "path": "pricing.py",
                                "old": "price * discount_percent / 100",
                                "new": "price * (1 - discount_percent / 100)",
                                "expected_version": version})}}
                    return {"choices": [{"message": {"role": "assistant", "content": None,
                                                     "tool_calls": [call]}}],
                            "model": "editor/model",
                            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}
                call = {"id": "test-1", "type": "function",
                        "function": {"name": "run_tests", "arguments": "{}"}}
                return {"choices": [{"message": {"role": "assistant", "content": None,
                                                 "tool_calls": [call]}}],
                        "model": "editor/model",
                        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}

        architect, editor = Architect(), Editor(self.runner)
        status = run_agent("Fix the discount calculation", editor, self.runner, self.ledger,
                           architect_client=architect)
        self.assertEqual(status, "tests_passed")
        self.assertEqual(architect.calls, 1)
        self.assertIsNone(architect.tools)
        self.assertIn("architect_plan", editor.state)
        self.assertIn("Fix the discount formula", editor.state["architect_plan"])
        events = self.ledger.data["events"]
        self.assertEqual([event["kind"] for event in events].count("architect_plan"), 1)
        self.assertEqual({event.get("model") for event in events if event["kind"] == "model"},
                         {"architect/model", "editor/model"})
        self.assertEqual(receipt(self.ledger.data)["architect_plans"], 1)
        self.assertTrue(receipt(self.ledger.data)["usage_complete"])

    def test_architect_failure_does_not_block_editing(self):
        class BrokenArchitect:
            def complete(self, messages, tools, max_tokens=1024, **kwargs):
                raise RuntimeError("Service unavailable")

        class Editor:
            def complete(self, messages, tools, max_tokens=1024, **kwargs):
                call = {"id": "map-1", "type": "function",
                        "function": {"name": "list_files", "arguments": "{}"}}
                return {"choices": [{"message": {"role": "assistant", "content": None,
                                                 "tool_calls": [call]}}],
                        "model": "editor/model",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}

        status = run_agent("Fix the discount calculation", Editor(), self.runner, self.ledger,
                           max_steps=1, architect_client=BrokenArchitect())
        self.assertEqual(status, "step_limit")
        bill = receipt(self.ledger.data)
        self.assertEqual(bill["failed_model_requests"], 1)
        self.assertFalse(bill["usage_complete"])
        self.assertEqual(bill["architect_plans"], 0)

    def test_fallback_is_recorded_in_receipt(self):
        class Flaky:
            def consume_fallback(self):
                event = getattr(self, "pending", None)
                self.pending = None
                return event

            def complete(self, messages, tools, max_tokens=1024, **kwargs):
                self.pending = {"from_model": "primary", "to_model": "backup", "status": 429}
                call = {"id": "list-1", "type": "function",
                        "function": {"name": "list_files", "arguments": "{}"}}
                return {"choices": [{"message": {"role": "assistant", "content": None,
                                                 "tool_calls": [call]}}],
                        "model": "backup",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}

        run_agent("Fix the discount calculation", Flaky(), self.runner, self.ledger, max_steps=1)
        bill = receipt(self.ledger.data)
        self.assertEqual(bill["model_fallbacks"], 1)
        self.assertTrue(bill["usage_complete"])


if __name__ == "__main__":
    unittest.main()
