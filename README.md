# GitNit

GitNit is a terminal UI for reviewing GitHub pull requests and issues with AI-assisted analysis.

It shows paginated PR and issue lists, opens detail screens with risk/summary analysis, and can use provider-backed models for review generation. Current provider support includes Claude Code and Gemini.

## Install From Source

For a global `gitnit` command that still runs from this source tree:

```bash
uv tool install --editable .
gitnit --help
```

## Requirements

GitNit needs a GitHub token:

```bash
export GITHUB_TOKEN=...
```

Or if using Gemini:

```bash
export GEMINI_API_KEY=...
```

Keep API keys in your shell environment or secret manager, not in `gitnit.toml`.

## Usage

Run against a repository:

```bash
gitnit --repo owner/repo
```

Use Gemini:

```bash
gitnit --repo owner/repo --provider gemini --model gemini-2.5-pro
```

Use the configured repository/provider:

```bash
gitnit
```

Show resolved config:

```bash
gitnit --show-config
```

## Configuration

GitNit loads config in this order:

```text
~/.config/gitnit/gitnit.toml
./gitnit.toml
./.gitnit.toml
--config /path/to/gitnit.toml
```

Later entries override earlier ones.

Example:

```toml
[ai]
provider = "gemini"
model = "gemini-2.5-pro"
prompt_version = "v3"

[github]
repo = "owner/repo"
cache_ttl_seconds = 600
poll_interval_seconds = 300
```

A fuller example is available in [gitnit.example.toml](gitnit.example.toml).

## Keybindings

Common keys:

```text
Up/Down   Navigate list items
Enter     Open selected item
Tab       Switch between PRs and issues
r         Refresh current view
s         Toggle issue sort
i         Show runtime info
?         Show help
c         Copy review/fix text on detail screens
Esc       Go back / close modal
q         Quit
```

## Providers

Current status:

```text
claude-code   Implemented via claude-agent-sdk
gemini        Implemented via google-genai
openai        Not implemented yet
openrouter    Not implemented yet
```

Provider selection is cache-aware. Analysis cache keys include repository, PR/issue, provider, model, prompt version, and schema version so switching providers does not reuse another provider's analysis.

## Development

Run syntax validation:

```bash
uv run python -m compileall src/gitnit
```

Run the CLI from source:

```bash
uv run gitnit --help
```
