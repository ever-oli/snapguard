# snapguard

Official CLI package for keeping opencode/Cursor snapshot growth under control.

## Install (local dev)

```bash
uv tool install --force /Users/ever/Documents/GitHub/snapguard
```

## Install via Homebrew (planned)

```bash
brew tap ever-oli/tap
brew install snapguard
```

## Install via PyPI (planned)

```bash
uv tool install snapguard
# or
pipx install snapguard
```

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
