# Spira MCP Server

A small [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server
that gives AI agents tools for managing Spira (SpiraTest / SpiraTeam /
SpiraPlan) test cases. It works with any MCP client (Claude Desktop, Claude
Code, or any other client that can launch a stdio MCP server).

## Tools

- `spira_list_test_cases`
- `spira_get_test_case`
- `spira_create_test_case`
- `spira_update_test_case`
- `spira_delete_test_case` (destructive: permanently deletes the test case)
- `spira_list_lookup_values`: resolve status / type / priority names to ids
- `spira_list_test_steps` / `spira_add_test_step`: structured "Step / Expected
  Result" rows, separate from the test case's free-text description

Once connected, you can hand an agent a requirements document or spec and ask
it to generate and create test cases directly in Spira.

## Status

Built and used against a Spira instance for test-case management. The unit
tests mock the Spira REST API, so they check request building and error
handling, not Spira's server-side behaviour. The Spira REST endpoints for
requirements and documents are not covered yet.

## 1. Get your Spira credentials

1. Log into Spira, go to **My Profile**, and copy your **API Key**.
2. Note your Spira URL. For SaaS this is `https://yourcompany.spiraservice.net`.
3. Note the numeric **Project Id** you want to work in (visible in the URL when
   you have a project open, e.g. `.../PR3/...` means project id 3).

## 2. Install

Requires Python 3.10+.

```bash
git clone https://github.com/alexplds/spira-mcp-server.git
cd spira-mcp-server
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

This installs a `spira-mcp` command (also runnable as `python -m spira_mcp`).
The server speaks MCP over stdio, so you normally don't run it by hand; your
MCP client launches it.

## 3. Configure your MCP client

Configuration is read from environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `SPIRA_BASE_URL` | yes | e.g. `https://yourcompany.spiraservice.net` |
| `SPIRA_USERNAME` | yes | Your Spira username |
| `SPIRA_API_KEY` | yes | Your API key (My Profile in Spira) |
| `SPIRA_API_VERSION` | no | REST API version segment, default `v6_0` |
| `SPIRA_DEFAULT_PROJECT_ID` | no | Project used when a tool call omits `project_id` |
| `SPIRA_TIMEOUT` | no | HTTP timeout in seconds, default `30` |

**Claude Code**:

```bash
claude mcp add spira \
  -e SPIRA_BASE_URL=https://yourcompany.spiraservice.net \
  -e SPIRA_USERNAME=your.username \
  -e SPIRA_API_KEY=your-api-key-here \
  -e SPIRA_DEFAULT_PROJECT_ID=1 \
  -- /absolute/path/to/spira-mcp-server/.venv/bin/spira-mcp
```

(see `claude mcp add --help`), or edit `.mcp.json` / `~/.claude.json` directly.

**Claude Desktop**: edit the config file (Settings → Developer → Edit Config
opens the same file):

| OS | Config file |
|----|-------------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "spira": {
      "command": "/absolute/path/to/spira-mcp-server/.venv/bin/spira-mcp",
      "env": {
        "SPIRA_BASE_URL": "https://yourcompany.spiraservice.net",
        "SPIRA_USERNAME": "your.username",
        "SPIRA_API_KEY": "your-api-key-here",
        "SPIRA_API_VERSION": "v6_0",
        "SPIRA_DEFAULT_PROJECT_ID": "1"
      }
    }
  }
}
```

On Windows, `command` is the path to `.venv\Scripts\spira-mcp.exe` instead
(JSON needs `\\` for backslashes), e.g.
`"C:\\Users\\you\\spira-mcp-server\\.venv\\Scripts\\spira-mcp.exe"`.

Any other MCP client works the same way: launch `spira-mcp` (or
`python -m spira_mcp`) as a stdio server with the environment variables above.

Restart your client afterwards so it picks up the new server.

## 4. Try it

In a chat with your agent:

> Using the Spira tools, list the first 10 test cases in the project.

> Here's our login-flow spec [paste or attach]. Generate test cases covering
> the happy path and the three error states, and create them in Spira under
> folder 12.

## Notes on field ids

Spira's `TestCaseStatusId`, `TestCaseTypeId`, `TestCasePriorityId`, and
`TestCaseFolderId` are numeric ids specific to your instance's configured
lookup lists (e.g. "Not Run", "Passed" for status). This server passes `0` for
status/type by default when creating a test case, which tells Spira to use your
project's default values.

Call `spira_list_lookup_values` to have the agent resolve a status / type /
priority by name instead of guessing ids. These lists are defined per
**project template**, not per project, so the tool looks up the project's
`ProjectTemplateId` first (`GET projects/{project_id}`), then calls
`project-templates/{template_id}/test-cases/types`, `.../statuses`, and
`.../priorities`.

## Notes on test steps

Spira stores a test case's step-by-step actions (`Description` /
`ExpectedResult` / `SampleData` per row) as a separate resource from the test
case's own `Description` field. Use `spira_add_test_step` to add structured
steps instead of writing them into the test case description as plain text.

Spira rejects an explicit `null` for `Position` / `SampleData` /
`ExpectedResult` on creation (400 Bad Request), so omit the field instead of
passing null. `spira_add_test_step` does this when you leave an argument unset.

## Notes on updates

Spira uses optimistic concurrency: every update must include the current
`ConcurrencyDate` of the record, or it's rejected. `spira_update_test_case`
handles this automatically by fetching the current test case first, then
merging your changes into it before sending the update.

## Design notes

- **Async `httpx`**: all tools are `async` and use `httpx.AsyncClient`.
- **stdio transport**: the client launches the server as a local subprocess.
  There is no network listener.
- **Per-user API keys**: each person runs their own local copy with their own
  Spira username and API key, so tool calls run with that user's own
  permissions. Nothing is shared or hosted.
- **Errors**: HTTP responses with status >= 400 raise a `RuntimeError`
  containing the status code, the request, and the first 500 characters of the
  response body. Missing configuration raises a `RuntimeError` at call time.
- **Config is read at call time** from the environment, not at import time.

## Security

Your `SPIRA_API_KEY` grants whatever access your Spira user account has. Don't
commit it to source control. The `env` block in your MCP client's config
(outside this repo) is the right place for it. `.env` files are git-ignored,
and `.env.example` contains placeholders only.

`spira_delete_test_case` permanently deletes data, so consider requiring
confirmation for it in your MCP client's tool-approval settings.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pytest
ruff check .
```

Tests use `pytest`, `pytest-asyncio` and `respx` to mock the Spira REST API, so
no network access or Spira instance is needed.

## License

MIT, see [LICENSE](LICENSE).
