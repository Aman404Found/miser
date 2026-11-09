# Evaluation method — established before measurements

No real-agent efficiency result has been measured yet. Offline demo fixtures validate mechanics only.

## Compare complete tasks

- Pin each repository, issue/task, acceptance command, dependency environment, and model identifier.
- Run a real OSS coding agent and MISER through the same Bifrost gateway/model configuration.
- Disable gateway response caching for the primary cold comparison; report cache-enabled experiments separately.
- Preserve initial failing checks, final full acceptance results, patches, failures, token usage, search credits if returned, and wall time.
- The user-configured command is the acceptance contract. Passing it does not establish correctness beyond its coverage. Protect benchmark checks outside the editable workspace for trustworthy evaluation.
- Use the same per-task spending/timeout limits where the baseline supports them; publish differences.
- Compare success rate and total tokens per solved task together. Include failed-run spending: total suite tokens / number of solved tasks. Also show paired task-level results and median tokens for tasks both systems solved.
- Repeat runs if resources permit and publish counts and variation. Temperature zero alone does not guarantee repeatability.
- Label version-sensitive tasks ahead of time and report them separately. Do not engineer or script a competing agent's failure for the demo.

## Accounting

Every model response contributes its reported prompt, completion, and total usage once. Tool-output context estimates are not separately billed tokens. Missing model usage is unknown, not free; the current host stops immediately and marks the receipt incomplete. Transport errors may have incurred remote spend: failed network calls also make accounting incomplete.

Search API credits are separate from model tokens. Search-based judgments, once implemented, must also contribute their model usage. Do not infer freshness from Tavily's relevance score. Do not present the retrieval timestamp as the source's publication timestamp.

The preflight budget estimates UTF-8 bytes / 4 and reserves output tokens. Actual tokenization varies; a single response can exceed the requested budget. Report that explicitly. Model request history is bounded; older tool observations expire, which may increase rereads or harm solve rate. Measure the tradeoff.

## Ablations planned

Real OSS agent; MISER focused context and bounded history; MISER with structural graph; MISER with live evidence checks. Current implementation does not yet provide a complete evaluation harness or assert benefits from any of these components.
