---
name: Create GitHub private repo
overview: Re-authenticate the GitHub CLI, then create a private repo and push the existing commit.
todos:
  - id: reauth
    content: Re-authenticate `gh` CLI (interactive — user must complete browser/device flow)
    status: completed
  - id: create-push
    content: Run `gh repo create ad-engine --private --source=. --remote=origin --push`
    status: completed
  - id: verify
    content: Verify repo exists and is private
    status: completed
isProject: false
---

# Create Private GitHub Repo

## Current State

- Local git repo exists at `/Users/n0destradamus/ad-engine` with 1 commit (`66e821d Phase 0: project scaffold, dependencies, and build guide`)
- No remote is configured yet
- `.gitignore` already excludes `.venv/`, `.env`, `__pycache__/`, etc.
- GitHub CLI is installed (`/opt/homebrew/bin/gh`) but the token for account `weeb3dev` is invalid

## Blockers

- `**gh auth` needs re-login** — run `gh auth login -h github.com` interactively to refresh the token (this requires browser/device flow)
- **GitHub MCP is also errored** — check MCP status in Cursor Settings if you'd prefer that route

## Steps (after auth is fixed)

1. **Re-authenticate GitHub CLI**

```
   gh auth login -h github.com
   

```

   Follow the interactive prompts (browser or token paste).

1. **Create private repo and push**

```
   gh repo create ad-engine --private --source=. --remote=origin --push
   

```

   This creates the repo under `weeb3dev/ad-engine`, adds it as the `origin` remote, and pushes the existing commit in one command.

1. **Verify**

```
   gh repo view weeb3dev/ad-engine --web
   

```

