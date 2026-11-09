"""Small OpenAI-compatible HTTP adapter; no SDK or provider lock-in."""

import http.client
import json
import os
import time
import urllib.error
import urllib.request


class StreamingUnsupported(RuntimeError):
    """The gateway did not accept an SSE request; a plain request is safe to try."""


class StreamInterrupted(RuntimeError):
    """The stream broke after data arrived; resending could bill the request twice."""


MAX_RETRY_AFTER_SECONDS = 30.0

# Status codes where another configured model, or a later attempt, may succeed.
RETRYABLE_STATUS = frozenset({429, 503})


class RemoteHTTPError(RuntimeError):
    """Transport error that keeps the HTTP status so callers can decide to fall back."""

    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _retry_after(headers):
    """Seconds requested by a Retry-After header, capped; HTTP-date values are ignored."""
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        seconds = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def http_error_message(status):
    # Response bodies may contain sensitive configuration; never echo them.
    hint = ""
    if status == 401:
        hint = (" — authentication rejected. For Bifrost inference, configure "
                "BIFROST_VIRTUAL_KEY with a gateway virtual key (not the Gemini provider key "
                "or dashboard setup token). Check gateway logs to identify the rejecting layer.")
    elif status == 403:
        hint = " — access denied; check gateway provider/model permissions and upstream API access."
    elif status == 429:
        hint = " — rate or quota limit; check gateway and provider limits before retrying."
    elif status == 503:
        hint = " — provider unavailable; a fallback model may be configured."
    return f"Remote service returned HTTP {status}{hint}"


def post_json(url, body, headers=None, timeout=60):
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RemoteHTTPError(error.code, http_error_message(error.code),
                              retry_after=_retry_after(getattr(error, "headers", None))) from None
    except urllib.error.URLError:
        raise RuntimeError("Cannot reach remote service; check its URL and availability") from None


def parse_models(value):
    """Split a comma-separated model list, preserving order and dropping duplicates."""
    if isinstance(value, (list, tuple)):
        value = ",".join(str(item) for item in value)
    seen, models = set(), []
    for model in str(value or "").split(","):
        model = model.strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


class ModelClient:
    # Status codes where another configured model is a reasonable substitute.
    RETRYABLE_STATUS = RETRYABLE_STATUS
    # A retryable failure is not final until the whole chain has been tried twice more.
    MAX_ATTEMPTS = 3
    BACKOFF_SECONDS = (2.0, 5.0)
    supports_streaming = True

    def __init__(self, model, base_url=None, fallbacks=None, on_notice=None, sleep=None):
        self.model = model
        self.sleep = sleep or time.sleep
        if fallbacks is None:
            fallbacks = os.getenv("MISER_FALLBACK_MODELS", "")
        self.fallbacks = [candidate for candidate in parse_models(fallbacks) if candidate != model]
        self.on_notice = on_notice
        self.base_url = (base_url or os.getenv("BIFROST_URL", "http://localhost:8080/openai")).rstrip("/")
        self._fallback_event = None

    @property
    def candidates(self):
        return [self.model, *self.fallbacks]

    def consume_fallback(self):
        """Return and clear the last fallback event, for the run ledger."""
        event, self._fallback_event = self._fallback_event, None
        return event

    def _headers(self):
        headers = {}
        if os.getenv("BIFROST_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["BIFROST_API_KEY"]
        if os.getenv("BIFROST_VIRTUAL_KEY"):
            headers["x-bf-vk"] = os.environ["BIFROST_VIRTUAL_KEY"]
        return headers

    def complete(self, messages, tools, max_tokens=1024, stream=False, on_token=None):
        headers = self._headers()
        candidates = self.candidates
        last_error = None
        for attempt in range(self.MAX_ATTEMPTS):
            exhausted = False
            for index, model in enumerate(candidates):
                body = {"model": model, "messages": messages,
                        "temperature": 0, "max_tokens": max_tokens}
                if tools:
                    body.update(tools=tools, tool_choice="auto")
                try:
                    if stream and on_token:
                        try:
                            return self._stream_complete(body, headers, on_token)
                        except StreamingUnsupported:
                            # Nothing was consumed, so a plain request cannot double-bill.
                            pass
                    return post_json(self.base_url + "/chat/completions", body, headers)
                except RemoteHTTPError as error:
                    last_error = error
                    if error.status not in self.RETRYABLE_STATUS:
                        raise
                    if index < len(candidates) - 1:
                        replacement = candidates[index + 1]
                        self._fallback_event = {"from_model": model, "to_model": replacement,
                                                "status": error.status}
                        if self.on_notice:
                            self.on_notice(f"· {model} returned HTTP {error.status}; "
                                           f"falling back to {replacement}")
                        continue
                    exhausted = True
            if not exhausted or attempt + 1 >= self.MAX_ATTEMPTS:
                break
            delay = self._delay(attempt, last_error)
            if self.on_notice:
                self.on_notice(f"· all models returned HTTP {last_error.status}; "
                               f"retrying in {delay:.0f}s "
                               f"({attempt + 1}/{self.MAX_ATTEMPTS - 1} retry)")
            self.sleep(delay)
        raise last_error or RuntimeError("No model candidate accepted the request")

    def _delay(self, attempt, error):
        """Honour the gateway's Retry-After, else back off exponentially."""
        if error is not None and error.retry_after:
            return error.retry_after
        backoff = self.BACKOFF_SECONDS
        return backoff[min(attempt, len(backoff) - 1)]

    def _stream_complete(self, body, headers, on_token, timeout=60):
        stream_body = dict(body)
        stream_body["stream"] = True
        stream_body["stream_options"] = {"include_usage": True}
        url = self.base_url + "/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(stream_body).encode(),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream", **headers}
        )
        content_parts = []
        tool_calls_map = {}
        finish_reason = None
        usage = None
        model_name = self.model

        try:
            response_context = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            raise RemoteHTTPError(error.code, http_error_message(error.code),
                                  retry_after=_retry_after(getattr(error, "headers", None))) from None
        except urllib.error.URLError:
            raise RuntimeError("Cannot reach remote service; check its URL and availability") from None
        received = False
        with response_context as response:
            headers = getattr(response, "headers", None)
            content_type = (headers.get("Content-Type") if headers is not None else None) or ""
            # Only reject a clearly non-SSE response; transports without headers are trusted.
            if content_type and "event-stream" not in content_type.lower():
                raise StreamingUnsupported(f"gateway returned {content_type}")
            try:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except ValueError:
                        continue
                    received = True
                    if chunk.get("model"):
                        model_name = chunk["model"]
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        piece = delta["content"]
                        content_parts.append(piece)
                        on_token(piece)
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {
                                    "id": tc.get("id", ""),
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc.get("id"):
                                tool_calls_map[idx]["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                tool_calls_map[idx]["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                tool_calls_map[idx]["function"]["arguments"] += fn["arguments"]
            except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
                if received:
                    raise StreamInterrupted(f"stream ended early ({type(error).__name__})") from None
                raise StreamingUnsupported("stream could not start") from None
        if not received:
            raise StreamingUnsupported("stream carried no events")

        tool_calls = [tool_calls_map[k] for k in sorted(tool_calls_map.keys())] if tool_calls_map else None
        message = {
            "role": "assistant",
            "content": "".join(content_parts) if content_parts else None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        res = {
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "model": model_name,
        }
        if usage:
            res["usage"] = usage
        return res
