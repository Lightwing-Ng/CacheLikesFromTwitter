# Native Agent and DevSpace Web Bridge

Documentation version: `v2.1.0`

The Agent workspace has two execution paths:

- ChatGPT is the default native path. It runs the Codex CLI bundled with the signed-in ChatGPT
  desktop app, enters the selected project directly, follows project instruction files, and uses
  the `workspace-write` sandbox with automatic approval review.
- Gemini and Grok retain the optional DevSpace web bridge. That path opens the selected signed-in
  browser session and requires a previously connected DevSpace MCP app.

The native ChatGPT path does not require a custom ChatGPT App, public tunnel, model API key,
DevSpace Owner password, or a manually started MCP runtime.

## Native ChatGPT Agent

1. Sign in to the ChatGPT desktop app with the ChatGPT subscription used for Agent work. An API-key-only Codex login is not reported as subscription-ready.
2. Open `/agent` and choose the local project.
3. Keep Platform set to ChatGPT.
4. Enter the task and press Enter. Use Shift+Enter for a newline.

The page streams bounded activity metadata such as command names and exit status. Command output is
not copied into the polling payload, and obvious secret assignments are redacted. The final Agent
message appears as escaped, server-rendered Markdown only after Codex exits successfully with a
non-empty response. Stop request ends the exact Codex process group for that task.

## Optional DevSpace web bridge

The bridge integrates the local checkout at `/Users/lightwing/Desktop/openSource/devspace` as an
isolated MCP runtime. It is retained for web products that cannot use the native Codex path.

### Security boundary

- The Agent page and every `/api/agent/*` route accept loopback clients only.
- DevSpace binds to `127.0.0.1` and runs in `codex` tool mode with subagents disabled.
- `DEVSPACE_ALLOWED_ROOTS` limits DevSpace to the selected project.
- The generated OAuth Owner password is stored with mode `0600` outside the repository. It is never
  returned by page markup or status APIs.
- Automatic OAuth approval runs only when the browser page origin exactly matches the configured
  DevSpace origin. The password is submitted to that exact form and is never included in a model
  prompt.
- The Flask app stops only a DevSpace process owned by its current runtime manager.

### Connection setup

1. In Settings → Agent, configure the local DevSpace port and the public HTTPS origin without
   `/mcp`.
2. Select Gemini or Grok on the Agent page and start MCP.
3. In the selected product's developer/MCP interface, add the HTTPS endpoint ending in `/mcp`.
4. Complete the one-time connection flow. The Agent page becomes ready only after authenticated MCP
   traffic reaches the current DevSpace runtime.

The web bridge rejects a response when no DevSpace tool call reaches the local runtime. It also
requires the answer text to remain stable after generation has stopped, so transient labels such as
`Thinking` cannot be reported as a completed task.

OpenAI's current developer guidance likewise requires an MCP server to be reachable through a
public HTTPS endpoint or Secure MCP Tunnel, and requires the connection to be added to a new
conversation's tools before testing:

- [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

## Upstream DevSpace

- Package: `@waishnav/devspace` `1.0.7`
- Source commit: `b5b4ab62a8718e1186aef815538741d9402f92ba`
- Required Node range: `>=22.19 <27`
- License: MIT; see [third-party notices](THIRD_PARTY_NOTICES.md)
