# DevSpace Subscription Web Agent

Documentation version: `v1.0.2`

The Agent workspace integrates the local checkout at
`/Users/lightwing/Desktop/openSource/devspace` as an isolated MCP runtime. It opens a cloned,
signed-in Safari, Microsoft Edge, or Google Chrome session and submits the task through the
selected ChatGPT, Gemini, or Grok web product. The selected web product performs the model work
under the active subscription and calls DevSpace for workspace tools; this integration does not
invoke a direct model inference API.

## Security boundary

- The Agent page and every `/api/agent/*` route accept loopback clients only.
- DevSpace binds to `127.0.0.1` and runs in `codex` tool mode with subagents disabled.
- `DEVSPACE_ALLOWED_ROOTS` limits workspaces to the configured root.
- The generated OAuth owner password is stored with mode `0600` outside the repository. It is not
  included in page markup or status payloads; the browser bridge submits it only to the exact
  configured loopback DevSpace OAuth form.
- The Flask app only stops a DevSpace process that it started itself.

## First connection

1. Select ChatGPT, Gemini, or Grok, select a browser session (Safari is the default), and enter the MCP port.
2. Create a public HTTPS tunnel to the configured local port, then enter its origin in the Agent sidebar.
3. Start MCP and verify that the local endpoint is ready.
4. In the selected web product's developer/MCP mode, add the HTTPS endpoint ending in `/mcp`.
5. Submit a task within the configured allowed workspace root. The local browser bridge handles the
   DevSpace Owner password approval automatically; no copy/paste step is required.

ChatGPT may pause for tool approval. The Agent page exposes the live conversation link so that the
approval remains an explicit user action.

The public tunnel is intentionally not provisioned automatically. It is an external security and
availability decision, and no supported tunnel client is currently installed on this host.

## Upstream

- Package: `@waishnav/devspace` `1.0.7`
- Source commit: `b5b4ab62a8718e1186aef815538741d9402f92ba`
- Required Node range: `>=22.19 <27`
- License: MIT; see [third-party notices](THIRD_PARTY_NOTICES.md)
