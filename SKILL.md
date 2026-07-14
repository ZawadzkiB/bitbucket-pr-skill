---
name: bitbucket-pr
description: >-
  List, read, comment on, and approve/request-changes on Bitbucket Cloud pull
  requests from the CLI — something the Atlassian MCP cannot do (it has Jira and
  Confluence tools but nothing for Bitbucket). Use whenever the user wants to
  review a Bitbucket PR, see which PRs are assigned to them, post inline or
  general PR comments, or set an approve / request-changes status. Needs a scoped
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
- read a PR's details, diff, or existing comments,
- leave a **comment** — general, or **inline** on a specific file + line,
- **approve** a PR or **request changes** (or remove either).

For anything in Jira/Confluence, use the normal Atlassian MCP tools — this skill
is only for Bitbucket PRs.

## Prerequisites (check first)

Auth is HTTP Basic (`email:token`). The script needs:

- `BITBUCKET_EMAIL` — the user's Atlassian account email
- `BITBUCKET_API_TOKEN` — a **scoped** token from <https://id.atlassian.com/manage-profile/security/api-tokens>
  ("Create API token with scopes"). App passwords are being removed — it must be a scoped API token.
- `BITBUCKET_WORKSPACE` / `BITBUCKET_REPO` — optional; auto-detected from the
  `origin` git remote when run inside a Bitbucket clone.
- `BITBUCKET_ACCOUNT_ID` — optional; only for `list --mine` / `--review` when the
  token lacks `read:user` scope.

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

The script lives next to this file at `scripts/bitbucket_pr.py`.

```bash
# which PRs are waiting for MY review?
python3 scripts/bitbucket_pr.py list --review

# all open PRs / a state / mine
python3 scripts/bitbucket_pr.py list
python3 scripts/bitbucket_pr.py list --state MERGED --mine

# read a PR
python3 scripts/bitbucket_pr.py show 2728
python3 scripts/bitbucket_pr.py diff 2728 --stat     # or without --stat for the full diff
python3 scripts/bitbucket_pr.py comments 2728

# comment
python3 scripts/bitbucket_pr.py comment 2728 --text "LGTM."
python3 scripts/bitbucket_pr.py comment 2728 --file path/to/File.java --line 42 --text "Null check?"

# review status (use --remove to undo)
python3 scripts/bitbucket_pr.py approve 2728
python3 scripts/bitbucket_pr.py request-changes 2728
```

Inline comments: `--line` is the line in the **new** file version, `--old-line`
the old version. Get the right number from the PR's diff (the `+` side).

## Safety — these post as the user

`comment`, `approve`, and `request-changes` are **outward-facing writes** that
other people see and that notify the PR author. Before running them:
- confirm the exact PR id and the comment/decision text with the user first,
- for inline comments, verify the file + line against the PR's current diff so the
  anchor lands correctly,
- read paths (`list`, `show`, `diff`, `comments`) are safe to run freely.

## Typical review flow

1. `list --review` → let the user pick a PR id.
2. `show <id>` + `diff <id>` (or `--stat`) → read the change.
3. Draft findings, confirm with the user.
4. `comment` (inline per finding and/or one general summary).
5. `approve` or `request-changes` once the user decides.
