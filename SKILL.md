---
name: bitbucket-pr
description: >-
  List, read, comment on, reply to and resolve comment threads, manage review tasks,
  and approve/request-changes on Bitbucket Cloud pull requests from the CLI —
  something the Atlassian MCP cannot do (it has Jira and Confluence tools but nothing
  for Bitbucket). Use whenever the user wants to review a Bitbucket PR, see which PRs
  are assigned to them, post or reply to PR comments, resolve threads, create or
  complete PR tasks, or set an approve / request-changes status. Needs a scoped
  Atlassian API token in the environment.
---

# Bitbucket pull requests

The Atlassian MCP server reaches Jira and Confluence but has **no Bitbucket
tools**, so it cannot touch pull requests. The Bitbucket Cloud REST API can. This
skill wraps it in one stdlib-only Python script.

## When to use

Reach for this when the user asks to:
- see open PRs, or specifically the ones **assigned to them** to review (so they
  can pick one),
- read a PR's details, diff, or existing comments (threaded),
- leave a **comment** — general, or **inline** on a specific file + line,
- **reply** to a comment and **resolve** / reopen a thread,
- create or complete **tasks** (review checklist items),
- **approve** a PR or **request changes** (or remove either).

For anything in Jira/Confluence, use the normal Atlassian MCP tools — this skill
is only for Bitbucket PRs.

## Prerequisites (check first)

**Fastest setup — run `configure` once** (recommended for a first run, or when a
call fails with 401/404):

```bash
python3 scripts/bitbucket_pr.py configure
```

It prompts for email / token / workspace / repo, verifies auth + repo access,
**auto-detects the user's account id** (if the token has `read:user` scope), and
saves everything to `~/.config/bitbucket-pr/config` (chmod 600). After that the
other commands need no env vars. Non-interactive: pass `--email/--token/--workspace/--repo/--account-id`.

Settings resolve **flag > env var > config file**. Auth is HTTP Basic (`email:token`). Names:

- `BITBUCKET_EMAIL` — the user's Atlassian account email
- `BITBUCKET_API_TOKEN` — a **scoped** token from <https://id.atlassian.com/manage-profile/security/api-tokens>
  ("Create API token with scopes"). App passwords are being removed — it must be a scoped API token.
- `BITBUCKET_WORKSPACE` / `BITBUCKET_REPO` — optional; auto-detected from the
  `origin` git remote when run inside a Bitbucket clone.
- `BITBUCKET_ACCOUNT_ID` — optional; only for `list --mine` / `--review` when the
  token lacks `read:user` scope. Find it as the `account_id` (`712020:xxxxxxxx-...`)
  on any PR/comment the user appears on (e.g. `comments <id>` output), or let the
  `read:user` scope resolve it automatically.

Required token scopes (a Confluence/Jira token will NOT work — it has no
Bitbucket scopes):

| Scope                          | Enables                          |
|--------------------------------|----------------------------------|
| `read:repository:bitbucket`    | diff, repo, file content         |
| `read:pullrequest:bitbucket`   | list / show / comments           |
| `write:pullrequest:bitbucket`  | comment / approve / request-changes |
| `read:user:bitbucket` (opt.)   | resolve "you" for `--mine`/`--review` |

The token must belong to an account that is a member of the workspace — otherwise
the repo 404s ("no access"). If any var is missing, ask the user to set it and
point them at `README.md`. A token pasted into chat lands in the transcript —
prefer having the user export it in their own shell, and remind them to revoke it.

## How to run

The script lives next to this file at `scripts/bitbucket_pr.py`. Run it by its
**absolute path** — the working directory is the user's project, not this folder:
- plugin install → `${CLAUDE_PLUGIN_ROOT}/scripts/bitbucket_pr.py`
- symlink install → `~/.claude/skills/bitbucket-pr/scripts/bitbucket_pr.py`

The examples below use the short form for brevity.

```bash
# one-time setup (writes ~/.config/bitbucket-pr/config)
python3 scripts/bitbucket_pr.py configure

# which PRs are waiting for MY review?
python3 scripts/bitbucket_pr.py list --review

# all open PRs / a state / mine
python3 scripts/bitbucket_pr.py list
python3 scripts/bitbucket_pr.py list --state MERGED --mine

# read a PR
python3 scripts/bitbucket_pr.py show 2728
python3 scripts/bitbucket_pr.py diff 2728 --stat     # or without --stat for the full diff
python3 scripts/bitbucket_pr.py comments 2728

# comment (general or inline); --task also creates a task on the comment
python3 scripts/bitbucket_pr.py comment 2728 --text "LGTM."
python3 scripts/bitbucket_pr.py comment 2728 --file path/to/File.java --line 42 --text "Null check?"
python3 scripts/bitbucket_pr.py comment 2728 --text "Please fix the leak" --task

# reply in a thread, and resolve / reopen a thread
python3 scripts/bitbucket_pr.py reply 2728 <comment-id> --text "Good point, done."
python3 scripts/bitbucket_pr.py resolve 2728 <comment-id>      # unresolve to reopen

# tasks (some teams track review items as tasks)
python3 scripts/bitbucket_pr.py tasks 2728
python3 scripts/bitbucket_pr.py task 2728 --text "Add a null guard" --on-comment <comment-id>
python3 scripts/bitbucket_pr.py task-done 2728 <task-id>       # task-reopen to undo

# review status (use --remove to undo)
python3 scripts/bitbucket_pr.py approve 2728
python3 scripts/bitbucket_pr.py request-changes 2728
```

Inline comments: `--line` is the line in the **new** file version, `--old-line`
the old version. Get the right number from the PR's diff (the `+` side).

## Command reference

| Command | Does | Key args |
|---|---|---|
| `configure` | One-time setup → `~/.config/bitbucket-pr/config` (verifies auth, auto-detects account id) | `--email --token --workspace --repo --account-id` (all optional; prompts in a terminal) |
| `list` | List PRs | `--state OPEN\|MERGED\|DECLINED`, `--mine`, `--review`, `--max-pages` |
| `show <id>` | PR details: title, branches, **source sha**, reviewers, approvals, comment/task counts | |
| `diff <id>` | Full unified diff | `--stat` for a diffstat |
| `comments <id>` | Comments as **threads** (replies indented, `[resolved]` marked) | |
| `comment <id> --text …` | Add a comment | `--file --line` (inline, new side) / `--old-line` (old side); `--task` also creates a task on it |
| `reply <id> <comment-id> --text …` | **Threaded reply** to a comment (yours or a reviewer's) | `--task` also creates a task on the reply |
| `resolve <id> <comment-id>` | Resolve (close) a comment thread | — |
| `unresolve <id> <comment-id>` | Reopen a resolved thread | — |
| `tasks <id>` | List tasks (`[x]`/`[ ]`, linked comment) | |
| `task <id> --text …` | Create a task | `--on-comment <comment-id>` to attach it to a comment |
| `task-done <id> <task-id>` | Mark a task resolved | (`task-reopen <id> <task-id>` to undo) |
| `approve <id>` | Approve the PR | `--remove` to withdraw |
| `request-changes <id>` | Request changes on the PR | `--remove` to withdraw |

`<id>` = PR number; `<comment-id>` / `<task-id>` come from the `comments` / `tasks` output.
`approve` / `request-changes` are **PR-level** (the whole PR), not per-comment — to close out one
thread use `resolve`, and for a must-fix item attach a `task`.

## Safety — these post as the user

`comment`, `reply`, `resolve`/`unresolve`, `task`/`task-done`, `approve`, and
`request-changes` are **outward-facing writes** that other people see and that
notify the PR author. Before running them:
- confirm the exact PR id and the comment/decision text with the user first,
- for inline comments, verify the file + line against the PR's current diff so the
  anchor lands correctly,
- read paths (`list`, `show`, `diff`, `comments`) are safe to run freely.

## Workflows

**Review a PR**
1. `list --review` → let the user pick a PR id.
2. `show <id>` + `diff <id>` (or `--stat`) → read the change.
3. Draft findings, confirm with the user.
4. `comment` (inline per finding and/or one general summary; add `--task` for must-fix items).
5. `approve` or `request-changes` once the user decides.

**Respond to feedback on your own PR**
1. `comments <id>` → read the threads; note the `<comment-id>`s that need a reply.
2. `reply <id> <comment-id> --text "…"` per thread (works for replying to a reviewer, or to someone
   who replied to your comment).
3. `resolve <id> <comment-id>` once a thread is addressed (`unresolve` to reopen).

**Work with tasks**
1. `tasks <id>` → see what's open.
2. Create one: `task <id> --text "…" [--on-comment <comment-id>]`, or `comment … --task` to leave a
   comment and turn it into a task in one step.
3. `task-done <id> <task-id>` when finished (`task-reopen` to undo).
