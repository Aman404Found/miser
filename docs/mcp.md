# External MCP tools

MISER has an opt-in, tools-only HTTP MCP client. It adds `mcp_list_tools` and
`mcp_call` to the selected profile only when `--mcp-config` is supplied. The normal
19-tool catalog and 9/12/19 inspect/research/coding profiles remain unchanged;
configured sessions expose 11/14/21 tools. External calls remain sequential.

## Configure a trusted endpoint

Create a JSON file **outside the repository**, for example
`/home/you/.config/miser/mcp.json`. MISER does not discover repository configs or
reuse ChatGPT's connectors. This is an example, not a working server or credential:

```json
{
  "servers": {
    "docs": {
      "url": "https://your-server.example/mcp",
      "read_only": true,
      "allowed_tools": ["lookup"],
      "auth_env": "MISER_DOCS_TOKEN",
      "protocol_version": "2026-07-28"
    }
  }
}
```

Replace the URL and tool names with those of a service you trust. If authentication
is needed, set the named environment variable through your normal secret manager.
Omit `auth_env` for an unauthenticated service. Inline credentials, URL queries,
userinfo and fragments are refused. File and parent-directory symlinks are refused;
the loader requires POSIX no-follow access. Keep the file host-controlled.

Public endpoints require HTTPS. A loopback endpoint such as
`http://127.0.0.1:9000/mcp` additionally requires `"allow_local": true`. Endpoint
hostnames are not DNS-pinned. This is explicit host permission to contact that
service, not general model URL access or an OS/network sandbox.

```bash
python3 -m miser mcp . --config /home/you/.config/miser/mcp.json --server docs
python3 -m miser chat . --mcp-config /home/you/.config/miser/mcp.json
```

The first command discovers metadata without a model; omit `--server` to list
aliases without network access. Inside chat, `/mcp` lists aliases and
`/mcp list docs` discovers allowed tools. The model can then request discovery and
one external call. Each call displays its alias, tool and arguments for fresh
approval. There is no "always approve" option. Headless `run`, batch and piped
stdin cannot approve calls. Discovery itself is permitted by the host config.

## Boundaries and accounting

- Only host-classified **read-only** tools are supported. Server annotations do
  not authorize anything. Obvious executor tool names are refused, but names and
  `read_only: true` cannot prove remote behavior. Trust and review the service:
  even a read can expose arguments, incur charges or have remote side effects.
- Remote descriptions, schemas and results are untrusted tool data, never system
  instructions or dynamically injected privileged tool definitions. Labels are not
  proof of model prompt-injection resistance.
- Authentication is a Bearer header from the selected environment variable.
  Known configured credentials are refused in arguments and redacted from results.
  Errors and MCP ledger events omit URLs, arguments, auth and remote error bodies.
  This is not a comprehensive secret scanner; never supply secrets as arguments.
- At most four servers and eight allowed tools per server; discovery is bounded
  to four pages of 100 entries each. Per task: 32 RPC attempts and eight tool-call
  attempts (including user rejections), plus up to four legacy cleanup requests.
  Discovery definitions are cached within the task, approval is never cached.
  Catalog budgeting includes omitted tool names; request an omitted tool's
  definition individually with `mcp_list_tools(server=..., tool=...)`.
- Responses have a 256,000-byte cap, a 15-second socket timeout and a deadline
  checked between reads at 30 seconds. Cancellation is checked between reads;
  blocked socket operations can delay it. Arguments are capped at 16,000 encoded
  bytes; returned text at 8,000 characters; catalog output at 10,000 encoded bytes.
- No redirects, environment proxies or automatic retries. Disconnects fail rather
  than replaying a potentially charged call. Ledger RPC completion means protocol
  success, not known service billing. MCP charges are unknown; they are not model
  provider tokens or a zero-cost claim. Legacy cleanup failures are recorded and
  do not replace the task outcome.

## Protocol scope and verification

The default pins the [2026-07-28 HTTP protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
with per-request version/client metadata and JSON or SSE responses. Set
`protocol_version` to `2025-11-25` explicitly for the
[legacy initialize/session lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle).
There is no automatic downgrade. Legacy session IDs are sent only to the configured
endpoint and cleaned up with DELETE when the task ends.

This subset excludes stdio/process launches, OAuth, mutating tools, custom schema
headers, resources, prompts, sampling, roots, subscriptions, task/input-required
flows and binary results. Unsupported tools/responses fail closed or report omitted
content. A service requiring these features will need a separate reviewed increment.

`tests/test_mcp.py` uses fake transports and simulated TUI key events. It covers
wire metadata, legacy handshake/cleanup, discovery, approvals, credential refusal,
redaction, limits, concurrency, JSON/SSE and failure paths without socket listeners.
No live MCP service, Meko integration or live model use of MCP has been verified.
