# Live testing

## Context-cost diagnostics

New coding runs record a `model_request` event before each editor call. It contains
size estimates for instructions, tool definitions, state, and retained history,
without saving those prompt bodies. `/receipt full` displays aggregate estimates
under `request_component_tokens_estimate`; the ledger contains each call's breakdown.
These use UTF-8 bytes / 4, not a provider tokenizer. They are never added to actual
provider usage. Currently this breakdown covers editor calls, not architect,
conversational, or evidence-review calls, nor separate attempts within client fallbacks.
Use actual reported input/output tokens to evaluate changes in spending.

Run these commands from the fresh-code project directory on the computer running
Bifrost. Keep Bifrost running, configure Gemini, and disable response caching.
Use the exact provider-prefixed model identifier shown by your gateway.

If inference returns HTTP 401, create a Bifrost virtual key that allows Gemini
and your selected model, then supply it to the same terminal as MISER:

```bash
read -rsp 'Bifrost virtual key: ' BIFROST_VIRTUAL_KEY
echo
export BIFROST_VIRTUAL_KEY
```

This is a gateway key, distinct from the Google AI Studio key stored in Bifrost.
Dashboard setup tokens authenticate setup/admin operations, not ordinary inference.
Use gateway logs to distinguish a gateway refusal from an upstream authentication failure.

```bash
python3 -m unittest discover -s tests -q
python3 -m miser inspect examples/python_bug --map --query 'pricing discount'
read -rp 'Bifrost model identifier: ' MISER_MODEL
export MISER_MODEL
python3 -m miser smoke --language python
```

This spends API tokens. The smoke test edits a disposable copy, runs real tests,
and writes a ledger. Its approximate budget is 12,000 tokens and eight steps;
one response may exceed the preflight estimate. Keep the printed run path.

If that succeeds:

```bash
python3 -m miser smoke --language javascript
python3 -m miser evaluate --repeats 1
```

The evaluation starts two additional model runs, one per language. Its report
counts failed-run spend. These synthetic tasks check integration, not real-world
efficiency or correctness beyond their acceptance tests.

For Tavily, supply the API key to the terminal running MISER. Tavily CLI OAuth
and keyless setup do not automatically configure MISER's direct API adapter.

```bash
read -rsp 'Tavily API key: ' TAVILY_API_KEY
echo
export TAVILY_API_KEY
python3 -m miser verify \
  --claim 'Python asyncio.run cannot be called when another asyncio event loop is running in the same thread' \
  --version '3.12' --domain docs.python.org --judge-model "$MISER_MODEL"
```

The model verdict is provisional and may abstain. Missing evidence is not a false
claim verdict. Review output and receipt separately from the coding test results.

## Send back

Send the command, terminal error/output, and the generated report or ledger for
these public demo fixtures. Never send API keys or a gateway configuration dump.
For private repositories, redact task text, paths, test output, and source details
before sharing receipts. HTTP 401/403 usually needs gateway authentication checked;
429 usually needs quota/rate limits checked. Do not repeatedly rerun paid tests
before investigating the first failure.
