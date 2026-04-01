# snapguard

Official CLI package for keeping opencode/Cursor snapshot growth under control.

## Install (local dev)

```bash
uv tool install --force /Users/ever/Documents/GitHub/snapguard
```

## Install via Homebrew

```bash
brew tap ever-oli/homebrew-tap
brew install ever-oli/homebrew-tap/snapguard
```

## Install via PyPI

```bash
uv tool install snapguard
# or
pipx install snapguard
```

Note: PyPI publishing is wired via GitHub Actions on `v*` tags. First-time setup requires creating the `snapguard` project on PyPI and adding a Trusted Publisher for repo `ever-oli/snapguard`, workflow `.github/workflows/publish-pypi.yml`, environment `pypi`.

## Commands

```bash
snapguard --interactive
snapguard --status
snapguard --dry-run
snapguard --schedule hourly --cap-gb 5

# short alias
sg --interactive
```

## What it monitors

- `~/.local/share/opencode/snapshot`
- `~/Library/Application Support/Cursor/User/workspaceStorage`
- `~/Library/Application Support/Cursor/snapshots`
- `~/Library/Application Support/Cursor/User/globalStorage`
