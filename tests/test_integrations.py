import json
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miser.client import ModelClient
from miser.ledger import Ledger
from miser.verification import DEFAULT_SEARCH_URL, EvidenceSearch, search_endpoint


class IntegrationTests(unittest.TestCase):
    def test_openai_compatible_http_protocol(self):
        # Transport fixture: this environment does not permit binding sockets.
        payload = {"choices": [{"message": {"content": "ok"}}],
                   "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}
        with patch.dict(os.environ, {"BIFROST_VIRTUAL_KEY": "fixture-not-a-secret"}), patch(
            "miser.client.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())
        ) as transport:
            client = ModelClient("test/model", "http://localhost:8080/openai")
            result = client.complete([{"role": "user", "content": "test"}], [], max_tokens=50)
        request = transport.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "http://localhost:8080/openai/chat/completions")
        self.assertEqual(body["model"], "test/model")
        self.assertEqual(body["max_tokens"], 50)
        self.assertEqual(request.get_header("X-bf-vk"), "fixture-not-a-secret")
        self.assertEqual(result["usage"]["total_tokens"], 3)

    def test_stream_complete_sse_protocol(self):
        sse_lines = [
            b"data: " + json.dumps({"choices": [{"delta": {"content": "Hello"}}], "model": "test/model"}).encode() + b"\n\n",
            b"data: " + json.dumps({"choices": [{"delta": {"content": " world!"}}], "model": "test/model"}).encode() + b"\n\n",
            b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}).encode() + b"\n\n",
            b"data: [DONE]\n\n"
        ]
        tokens = []
        with patch.dict(os.environ, {"BIFROST_VIRTUAL_KEY": "fixture-key"}), patch(
            "miser.client.urllib.request.urlopen", return_value=io.BytesIO(b"".join(sse_lines))
        ):
            client = ModelClient("test/model", "http://localhost:8080/openai")
            result = client.complete(
                [{"role": "user", "content": "hi"}], [],
                stream=True, on_token=tokens.append
            )
        self.assertEqual(tokens, ["Hello", " world!"])
        self.assertEqual(result["choices"][0]["message"]["content"], "Hello world!")
        self.assertEqual(result["usage"]["total_tokens"], 7)

    def make_search(self, root, limit=3):
        return EvidenceSearch(Ledger(Path(root) / "ledger.json", mode="unit-test-fixture"), limit)

    def test_evidence_is_version_scoped_not_auto_verified(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"TAVILY_API_KEY": "fixture"}), patch(
            "miser.verification.post_json", return_value={"results": [
                {"url": "https://docs.example.org/v2/api", "content": "Candidate documentation"},
                {"url": "https://docs.example.org.evil.invalid/api", "content": "Not official"},
                {"url": "http://docs.example.org/api", "content": "Insecure"},
            ]}) as request:
            search = self.make_search(root)
            card = search.verify_claim("API accepts option", "2.0", ["docs.example.org"])
            self.assertEqual(card["verdict"], "unverified")
            self.assertIsNone(card["freshness_score"])
            self.assertIsNone(card["candidates"][0]["published_at"])
            self.assertEqual(card["applicable_version"], "2.0")
            self.assertEqual(len(card["candidates"]), 1)
            self.assertEqual(request.call_args.args[1]["include_domains"], ["docs.example.org"])

    def test_failed_searches_consume_attempt_limit(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"TAVILY_API_KEY": "fixture"}), patch(
            "miser.verification.post_json", side_effect=RuntimeError("offline")):
            search = self.make_search(root, limit=1)
            with self.assertRaises(RuntimeError):
                search.verify_claim("API accepts option", "2.0", ["docs.example.org"])
            with self.assertRaisesRegex(ValueError, "limit"):
                search.verify_claim("API accepts option", "2.0", ["docs.example.org"])
            self.assertEqual(search.ledger.data["events"][0]["status"], "error")

    def test_missing_key_does_not_invent_evidence(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "not configured"):
                self.make_search(root).verify_claim("Claim", "2", ["docs.example.org"])

    def make_search_in(self, root):
        return EvidenceSearch(Ledger(Path(root) / "ledger.json", mode="unit-test-fixture"), 3)

    def test_search_endpoint_defaults_to_https(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(search_endpoint(), DEFAULT_SEARCH_URL)
            self.assertTrue(search_endpoint().startswith("https://"))

    def test_loopback_http_test_double_is_allowed(self):
        for url in ("http://127.0.0.1:9999/search", "http://localhost:9999/search"):
            with self.subTest(url=url), patch.dict(os.environ, {"TAVILY_API_URL": url}):
                self.assertEqual(search_endpoint(), url)

    def test_non_loopback_or_non_https_endpoint_is_rejected(self):
        # A plain-HTTP search would leak the API key and claim text in clear text.
        for url in ("http://docs.example.org/search", "http://localhost.evil.invalid/search",
                    "ftp://api.tavily.com/search", "not-a-url"):
            with self.subTest(url=url), patch.dict(os.environ, {"TAVILY_API_URL": url}):
                with self.assertRaisesRegex(ValueError, "https"):
                    search_endpoint()

    def test_empty_results_are_no_evidence_not_an_error(self):
        for payload in ({}, {"results": None}, {"results": []}):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as root, patch.dict(
                        os.environ, {"TAVILY_API_KEY": "fixture"}), patch(
                        "miser.verification.post_json", return_value=payload):
                    search = self.make_search_in(root)
                    card = search.verify_claim("API accepts option", "2.0", ["docs.example.org"])
                    self.assertEqual(card["candidates"], [])
                    self.assertEqual(search.ledger.data["events"][-1]["status"], "no_evidence")

    def test_malformed_search_payload_is_error_not_evidence(self):
        for payload in (None, ["not", "an", "object"], {"results": "not-a-list"}, "text"):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as root, patch.dict(
                        os.environ, {"TAVILY_API_KEY": "fixture"}), patch(
                        "miser.verification.post_json", return_value=payload):
                    search = self.make_search_in(root)
                    with self.assertRaises(RuntimeError):
                        search.verify_claim("API accepts option", "2.0", ["docs.example.org"])
                    self.assertEqual(search.ledger.data["events"][-1]["status"], "error")

    def test_non_object_result_entries_are_skipped(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"TAVILY_API_KEY": "fixture"}), patch(
                "miser.verification.post_json", return_value={"results": [
                    "junk", None, {"title": "no url"}, {"url": 42},
                    {"url": "https://docs.example.org/api", "content": "ok"}]}):
            card = self.make_search_in(root).verify_claim("API accepts option", "2.0", ["docs.example.org"])
        self.assertEqual([c["url"] for c in card["candidates"]], ["https://docs.example.org/api"])

    def test_load_env_populates_unconfigured_variables(self):
        from miser.cli import load_env
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            env_file = Path(root) / ".env"
            env_file.write_text("BIFROST_VIRTUAL_KEY=vk-test-123\nMISER_MODEL=test-model\n# comment\n")
            load_env(env_file)
            self.assertEqual(os.environ.get("BIFROST_VIRTUAL_KEY"), "vk-test-123")
            self.assertEqual(os.environ.get("MISER_MODEL"), "test-model")
