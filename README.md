# bitbucket-pr-skill

**List, read, comment on, and approve / request-changes on Bitbucket Cloud pull
requests** from the command line — and as a [Claude Code](https://claude.ai/code) skill.

## Install

### A) Claude Code plugin marketplace (recommended)

In Claude Code:

```
/plugin marketplace add ZawadzkiB/bitbucket-pr-skill
/plugin install bitbucket-pr@bitbucket-pr-skill
/reload-plugins
```

Then set it up — just ask Claude *"configure bitbucket-pr"* (it runs the
`configure` step for you), or do it manually per [Configure](#2-configure).

### B) Manual — clone + symlink (for local dev / no marketplace)

```bash
git clone https://github.com/ZawadzkiB/bitbucket-pr-skill.git
cd bitbucket-pr-skill
mkdir -p ~/.claude/skills
ln -s "$(pwd)" ~/.claude/skills/bitbucket-pr
python3 scripts/bitbucket_pr.py configure
```

> Use **one** method, not both — installing the plugin while the symlink exists
> gives you two copies of the same `bitbucket-pr` skill. Remove the symlink
> (`rm ~/.claude/skills/bitbucket-pr`) before switching to the plugin.

Either way you still need a scoped API token — see [Get a scoped API token](#1-get-a-scoped-api-token).

## Why this exists

The Atlassian MCP server reaches Jira and Confluence but has **no Bitbucket
tools**, so an agent using it cannot touch pull requests. The Bitbucket Cloud
**REST API** can. This repo wraps that in a single, dependency-free Python script
and packages it as a Claude skill.

- No `pip install` — Python 3.8+ standard library only.
- `list` open PRs, and narrow to the ones **assigned to you** (`--review`) or that
  you authored (`--mine`) so you can pick what to review.
- `show` / `diff` / `comments` (threaded) to read a PR.
- `comment` — general, or **inline** on a specific file + line (`--task` also makes it a task).
- `reply` to a comment, `resolve` / `unresolve` a thread.
- `tasks` / `task` / `task-done` — track review items as Bitbucket tasks.
- `approve` / `request-changes` (with `--remove` to undo).
- Workspace/repo auto-detected from the `origin` git remote when run in a clone.

## Prerequisites

- Python 3.8+
- A Bitbucket **Cloud** repository
- A **scoped** Atlassian API token (below)

## 1. Get a scoped API token

App passwords are being removed (brownout 2026) — you need an **API token with
scopes**.

1. Open <https://id.atlassian.com/manage-profile/security/api-tokens>.
2. Click **Create API token with scopes**.
3. Choose **Bitbucket** and select:
   - `read:repository:bitbucket` — diff / repo / file content
   - `read:pullrequest:bitbucket` — list / show / comments
   - `write:pullrequest:bitbucket` — comment / approve / request-changes
   - `read:user:bitbucket` *(optional)* — resolve "you" for `--mine` / `--review`
4. **Copy the value now** — Atlassian shows it only once.

The token must belong to an account that is a **member of the workspace**, or the
repo returns 404 ("no access"). It is used with your Atlassian account **email**
as HTTP Basic auth (`email:token`).

## 2. Configure

### Recommended: `configure` (interactive)

```bash
python3 scripts/bitbucket_pr.py configure
```

It prompts for your email, token, and (optionally) workspace/repo, then:
- verifies the token and repo access,
- **auto-detects your account id** when the token has `read:user:bitbucket`,
- saves everything to `~/.config/bitbucket-pr/config` (chmod 600).

After that, no env vars are needed. Non-interactive (e.g. for an agent):

```bash
python3 scripts/bitbucket_pr.py configure \
  --email you@company.com --token "$TOKEN" \
  --workspace your-workspace --repo your-repo
```

### Or set environment variables (they override the saved config)

```bash
export BITBUCKET_EMAIL="you@company.com"
export BITBUCKET_API_TOKEN="paste-your-token"
# optional — auto-detected from the git remote when omitted:
export BITBUCKET_WORKSPACE="your-workspace"
export BITBUCKET_REPO="your-repo"
# optional — only for --mine/--review if the token lacks read:user scope:
export BITBUCKET_ACCOUNT_ID="712020:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Keep them in a local, gitignored `.env` and `source` it. Never paste the token
into a shared chat/transcript; if you do, revoke it afterwards.

### Finding your account id

The `account_id` (format `712020:xxxxxxxx-...`) is only needed for `--mine` /
`--review`. Easiest is to give the token the `read:user:bitbucket` scope — then
`configure` (and the filters) resolve it automatically. Without that scope, read
it off any API object where you appear: run `bitbucket_pr.py comments <pr-id>` on
a PR you've commented on, or look at a PR's reviewers — the `account_id` field is
yours.

## 3. Use it (CLI)

```bash
# which PRs are waiting for MY review?
python3 scripts/bitbucket_pr.py list --review

# all open PRs (auto-detects workspace/repo from the git remote)
python3 scripts/bitbucket_pr.py list
python3 scripts/bitbucket_pr.py list --state MERGED --mine

# read a PR
python3 scripts/bitbucket_pr.py show 2728
python3 scripts/bitbucket_pr.py diff 2728 --stat     # full diff without --stat
python3 scripts/bitbucket_pr.py comments 2728

# comment — general or inline; --task also creates a task on the comment
python3 scripts/bitbucket_pr.py comment 2728 --text "LGTM, one nit below."
python3 scripts/bitbucket_pr.py comment 2728 --file src/Foo.java --line 42 --text "Null check here?"

# threads: reply, resolve/reopen
python3 scripts/bitbucket_pr.py reply 2728 <comment-id> --text "Good point, done."
python3 scripts/bitbucket_pr.py resolve 2728 <comment-id>      # unresolve to reopen

# tasks (review checklist items)
python3 scripts/bitbucket_pr.py tasks 2728
python3 scripts/bitbucket_pr.py task 2728 --text "Add a null guard" --on-comment <comment-id>
python3 scripts/bitbucket_pr.py task-done 2728 <task-id>       # task-reopen to undo

# review status (use --remove to undo)
python3 scripts/bitbucket_pr.py approve 2728
python3 scripts/bitbucket_pr.py request-changes 2728
```

`--line` is the line in the **new** file version, `--old-line` the old version —
take the number from the `+`/`-` side of the PR diff.

## 4. Install as a Claude skill

Claude Code discovers personal skills in `~/.claude/skills/<name>/`. This repo's
root **is** a skill folder, so clone it and symlink it in:

```bash
git clone https://github.com/ZawadzkiB/bitbucket-pr-skill.git
cd bitbucket-pr-skill
mkdir -p ~/.claude/skills
ln -s "$(pwd)" ~/.claude/skills/bitbucket-pr
```

(A symlink means `git pull` updates the skill automatically. Prefer a copy?
`cp -R . ~/.claude/skills/bitbucket-pr`.) Then just ask, e.g.
*"which Bitbucket PRs are assigned to me?"* or *"review PR 2728"*, and Claude will
pick it up. Make sure the env vars are available to the shell Claude Code launches
from.

## Security notes

- The token grants your Bitbucket access — treat it like a password.
- `comment`, `approve`, and `request-changes` are **visible to others** and notify
  the PR author. The skill confirms intent before running them.
- Prefer short expiries; **revoke** tokens you no longer need at
  <https://id.atlassian.com/manage-profile/security/api-tokens>.
- The script sends the token only to `api.bitbucket.org` over HTTPS.

## Limitations

- Bitbucket **Cloud** only (uses `api.bitbucket.org` paths).
- `list` is scoped to one repository; `--mine`/`--review` need to resolve your
  account (via `read:user` scope or `BITBUCKET_ACCOUNT_ID`).
- Merging/declining PRs is intentionally not included (review-focused).
