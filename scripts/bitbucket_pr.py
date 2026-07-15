#!/usr/bin/env python3
"""
bitbucket_pr.py — list, read, comment on, and approve/request-changes Bitbucket
Cloud pull requests from the command line.

The Atlassian MCP server can reach Jira and Confluence but has NO Bitbucket
tools, so it cannot touch pull requests. The Bitbucket Cloud REST API can. This
tool wraps it with only the Python standard library (no `pip install`).

It can:
  * `configure` — save your email/token/workspace/repo/account-id once (and
    auto-detect your account id) so you don't juggle env vars,
  * list a repo's PRs, and narrow to the ones you authored (--mine) or are a
    reviewer on (--review) so you can pick what to review,
  * show a PR's details, diff (or diffstat), and existing comments (threaded),
  * add a comment — general, or inline on a specific file+line,
  * reply to a comment (threaded), and resolve / reopen comment threads,
  * create and complete tasks (standalone or attached to a comment),
  * approve, request changes, or remove either,
  * read CI pipelines, their steps, and step logs (pipelines / pipeline / pipeline-log).

Settings resolve in this order (first wins): CLI flag > environment variable >
saved config file (~/.config/bitbucket-pr/config). Auth is HTTP Basic
(email:token). The relevant names:
  BITBUCKET_EMAIL        your Atlassian account email          (--email)
  BITBUCKET_API_TOKEN    scoped Atlassian API token (see below)
  BITBUCKET_WORKSPACE    e.g. sl-technology     (else: git remote)  (--workspace)
  BITBUCKET_REPO         e.g. my-service        (else: git remote)  (--repo)
  BITBUCKET_ACCOUNT_ID   your account id, only needed for --mine/--review when
                         the token lacks read:user scope

Create the token at https://id.atlassian.com/manage-profile/security/api-tokens
("Create API token with scopes"), Bitbucket scopes:
  read:repository:bitbucket    diff / repo
  read:pullrequest:bitbucket   list / show / comments
  write:pullrequest:bitbucket  comment / approve / request-changes
  read:user:bitbucket          (optional) auto-resolve "you" for configure/--mine/--review
  read:pipeline:bitbucket      (optional) pipelines / pipeline / pipeline-log

Examples:
  bitbucket_pr.py configure                  # interactive setup (recommended first run)
  bitbucket_pr.py list --review              # PRs assigned to you for review
  bitbucket_pr.py show 2728
  bitbucket_pr.py diff 2728 --stat
  bitbucket_pr.py comment 2728 --file src/Foo.java --line 42 --text "Null check?"
  bitbucket_pr.py comment 2728 --text "Please fix the leak" --task   # comment + task on it
  bitbucket_pr.py reply 2728 826645669 --text "Good point, will do."
  bitbucket_pr.py resolve 2728 826645669          # unresolve to reopen
  bitbucket_pr.py tasks 2728
  bitbucket_pr.py task 2728 --text "Add a null guard" --on-comment 826645669
  bitbucket_pr.py task-done 2728 42
  bitbucket_pr.py approve 2728
  bitbucket_pr.py pipelines --pr 2733        # CI runs for a PR's branch
  bitbucket_pr.py pipeline 21414             # steps + status
  bitbucket_pr.py pipeline-log 21414 2       # log of step 2 (diagnose a failure)
"""
import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.bitbucket.org/2.0"
CONFIG_PATH = os.path.expanduser("~/.config/bitbucket-pr/config")
CONFIG = {}  # loaded in main()


def die(msg):
    sys.exit(f"error: {msg}")


def build_auth(email, token):
    return base64.b64encode(f"{email}:{token}".encode()).decode()


def load_config():
    cfg = {}
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    cfg[key.strip()] = val.strip()
    return cfg


def cfg(name, cli=None):
    """Resolve a setting: CLI flag (or env, via argparse default) > config file."""
    return cli or os.environ.get(name) or CONFIG.get(name)


def request(auth, method, url, data=None, headers=None, raw=False, soft=False):
    """Call the API. Returns parsed JSON (or text if raw). On HTTP error: die,
    unless soft=True (then return None so the caller can recover)."""
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Basic {auth}", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            if raw:
                return body.decode("utf-8", "replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        if soft:
            return None
        detail = e.read().decode("utf-8", "replace")[:800]
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except (ValueError, AttributeError):
            pass
        die(f"HTTP {e.code} on {method} {url[len(API):] or url}\n  {detail}")
    except urllib.error.URLError as e:
        die(f"network error on {method}: {e.reason}")


def paginate(auth, url, max_pages=100):
    """Follow `next` links, collecting `values`. Returns (items, truncated)."""
    items, pages = [], 0
    while url and pages < max_pages:
        page = request(auth, "GET", url)
        items.extend(page.get("values", []))
        url = page.get("next")
        pages += 1
    return items, bool(url)


def detect_repo():
    try:
        out = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None, None
    m = re.search(r"bitbucket\.org[:/]([^/]+)/([^/]+?)(?:\.git)?$", out)
    return (m.group(1), m.group(2)) if m else (None, None)


def resolve_me(auth):
    """Best-effort current-account id: env/config override, else GET /user (needs
    read:user scope). Returns None if neither is available."""
    acct = cfg("BITBUCKET_ACCOUNT_ID")
    if acct:
        return acct
    me = request(auth, "GET", f"{API}/user", soft=True)
    return me.get("account_id") if me else None


def repo_base(ws, repo):
    return f"{API}/repositories/{ws}/{repo}/pullrequests"


def html_link(pr):
    return pr.get("links", {}).get("html", {}).get("href", "")


def truncate(text, width):
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


# --- commands ---------------------------------------------------------------

def cmd_configure(args):
    """Interactive/flag-driven setup: verify auth, auto-resolve account id, save."""
    def ask(label, current, secret=False):
        if not sys.stdin.isatty():
            return current
        hint = ("(saved)" if secret and current else current) or ""
        suffix = f" [{hint}]" if hint else ""
        prompt = f"{label}{suffix}: "
        val = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        return val or current

    email = args.email or cfg("BITBUCKET_EMAIL")
    token = args.token or cfg("BITBUCKET_API_TOKEN")
    ws = args.workspace or cfg("BITBUCKET_WORKSPACE")
    repo = args.repo or cfg("BITBUCKET_REPO")
    account = args.account_id or cfg("BITBUCKET_ACCOUNT_ID")

    email = ask("Atlassian account email", email)
    token = ask("Scoped API token", token, secret=True)
    ws = ask("Workspace (blank = auto-detect from git remote)", ws)
    repo = ask("Repo (blank = auto-detect from git remote)", repo)

    if not email or not token:
        die("configure needs at least --email and --token (or run it in an interactive terminal)")

    auth = build_auth(email, token)
    print()
    me = request(auth, "GET", f"{API}/user", soft=True)
    if me and me.get("account_id"):
        account = me["account_id"]
        print(f"  auth OK — {me.get('display_name', '?')}  (account_id {account})")
    else:
        print("  token accepted, but couldn't read your account id "
              "(token lacks the read:user:bitbucket scope).")
        if not account:
            print("  -> add read:user:bitbucket and re-run, OR pass --account-id.")
            print("     Find it as the 'account_id' (712020:xxxxxxxx-...) on any PR or")
            print("     comment you appear on, e.g. `bitbucket_pr.py comments <id>` output.")

    d_ws, d_repo = detect_repo()
    vws, vrepo = ws or d_ws, repo or d_repo
    if vws and vrepo:
        ok = request(auth, "GET", f"{API}/repositories/{vws}/{vrepo}", soft=True)
        print(f"  repo access {vws}/{vrepo}: "
              + ("OK" if ok else "FAILED (404 — account not a member, or wrong slug)"))

    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    lines = [
        "# bitbucket-pr config — written by `bitbucket_pr.py configure`.",
        "# Keep private (chmod 600). Same-named environment variables override these.",
        f"BITBUCKET_EMAIL={email}",
        f"BITBUCKET_API_TOKEN={token}",
    ]
    if ws:
        lines.append(f"BITBUCKET_WORKSPACE={ws}")
    if repo:
        lines.append(f"BITBUCKET_REPO={repo}")
    if account:
        lines.append(f"BITBUCKET_ACCOUNT_ID={account}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(CONFIG_PATH, 0o600)
    masked = token[:8] + "…" if len(token) > 8 else "…"
    print(f"\nsaved {CONFIG_PATH} (chmod 600)  token={masked}")
    print("this file holds your token — treat it like a password; revoke at "
          "https://id.atlassian.com/manage-profile/security/api-tokens when done.")


def cmd_list(args, auth, ws, repo):
    state = args.state.upper()
    query = urllib.parse.urlencode({
        "state": state,
        "pagelen": 50,
        "fields": "+values.reviewers.account_id,+values.reviewers.display_name,"
                  "+values.participants.account_id,+values.participants.state",
    })
    prs, truncated = paginate(auth, f"{repo_base(ws, repo)}?{query}", max_pages=args.max_pages)

    me = None
    if args.mine or args.review:
        me = resolve_me(auth)
        if not me:
            die("could not resolve your account for --mine/--review: run "
                "`bitbucket_pr.py configure` with a token that has read:user:bitbucket, "
                "or set BITBUCKET_ACCOUNT_ID.")

    rows = []
    for pr in prs:
        author_id = pr.get("author", {}).get("account_id")
        reviewer_ids = [r.get("account_id") for r in pr.get("reviewers", [])]
        is_author = me is not None and author_id == me
        is_reviewer = me is not None and me in reviewer_ids
        if args.mine and not is_author:
            continue
        if args.review and not is_reviewer:
            continue
        role = ",".join(r for r, on in (("author", is_author), ("reviewer", is_reviewer)) if on) or "-"
        rows.append((pr, role))

    label = "; ".join(v for k, v in (("mine", "authored by you"),
                                     ("review", "assigned to you for review")) if getattr(args, k)) or "all"
    print(f"{len(rows)} {state} pull request(s) in {ws}/{repo} ({label}):\n")
    for pr, role in rows:
        print(f"  #{pr['id']:<5} {pr['state']:<8} [{role}]  "
              f"{truncate(pr.get('author', {}).get('display_name', '?'), 18):<18}  "
              f"{(pr.get('updated_on') or '')[:10]}  {truncate(pr.get('title'), 60)}")
        print(f"         {html_link(pr)}")
    if truncated:
        print(f"\n  (stopped at {args.max_pages} pages — narrow with --state/--mine/--review or raise --max-pages)")


def cmd_show(args, auth, ws, repo):
    pr = request(auth, "GET", f"{repo_base(ws, repo)}/{args.id}")
    src = pr.get("source", {}).get("branch", {}).get("name", "?")
    dst = pr.get("destination", {}).get("branch", {}).get("name", "?")
    src_commit = pr.get("source", {}).get("commit", {}).get("hash", "?")
    reviewers = ", ".join(r.get("display_name", "?") for r in pr.get("reviewers", [])) or "(none)"
    approvals = [p.get("user", {}).get("display_name", "?")
                 for p in pr.get("participants", []) if p.get("approved")]
    changes = [p.get("user", {}).get("display_name", "?")
               for p in pr.get("participants", []) if p.get("state") == "changes_requested"]
    print(f"#{pr['id']}  {pr['title']}")
    print(f"  state:       {pr['state']}{' (draft)' if pr.get('draft') else ''}")
    print(f"  author:      {pr.get('author', {}).get('display_name', '?')}")
    print(f"  branch:      {src} -> {dst}")
    print(f"  source sha:  {src_commit}   (use this to verify inline line anchors)")
    print(f"  reviewers:   {reviewers}")
    print(f"  approved by: {', '.join(approvals) or '(none)'}")
    print(f"  changes req: {', '.join(changes) or '(none)'}")
    print(f"  comments:    {pr.get('comment_count', 0)}   tasks: {pr.get('task_count', 0)}")
    print(f"  updated:     {(pr.get('updated_on') or '')[:19].replace('T', ' ')}")
    print(f"  link:        {html_link(pr)}")
    desc = (pr.get("description") or "").strip()
    if desc:
        print("\n  description:")
        for line in desc.splitlines():
            print(f"    {line}")


def cmd_diff(args, auth, ws, repo):
    if args.stat:
        items, _ = paginate(auth, f"{repo_base(ws, repo)}/{args.id}/diffstat?pagelen=100")
        add = rem = 0
        for v in items:
            a, r = v.get("lines_added") or 0, v.get("lines_removed") or 0
            add, rem = add + a, rem + r
            path = (v.get("new") or v.get("old") or {}).get("path", "?")
            print(f"  {v.get('status', ''):9} +{a:<5} -{r:<5} {path}")
        print(f"\n  {len(items)} file(s), +{add} -{rem}")
    else:
        print(request(auth, "GET", f"{repo_base(ws, repo)}/{args.id}/diff", raw=True))


def _comment_location(c):
    inline = c.get("inline")
    return f"{inline['path']}:{inline.get('to') or inline.get('from')}" if inline else "(general)"


def cmd_comments(args, auth, ws, repo):
    query = urllib.parse.urlencode({"pagelen": 100, "fields": "+values.resolution"})
    items, _ = paginate(auth, f"{repo_base(ws, repo)}/{args.id}/comments?{query}")
    live = [c for c in items if not c.get("deleted")]
    children, roots = {}, []
    for c in live:
        parent = (c.get("parent") or {}).get("id")
        (children.setdefault(parent, []) if parent else roots).append(c)

    def show(c, depth):
        pad = "    " * depth
        who = c.get("user", {}).get("display_name", "?")
        flags = "  [resolved]" if c.get("resolution") is not None else ""
        loc = f" @ {_comment_location(c)}" if depth == 0 else ""
        print(f"{pad}  [{c['id']}] {who}{loc}{flags}")
        print(f"{pad}      {truncate(c.get('content', {}).get('raw', ''), 140)}")
        for reply in sorted(children.get(c["id"], []), key=lambda x: x["id"]):
            show(reply, depth + 1)

    for c in sorted(roots, key=lambda x: x["id"]):
        show(c, 0)
    print(f"\n  {len(live)} comment(s) on #{args.id} ({len(roots)} thread(s))")


def _post_comment(auth, ws, repo, pr_id, text, inline=None, parent_id=None):
    payload = {"content": {"raw": text}}
    if inline:
        payload["inline"] = inline
    if parent_id is not None:
        payload["parent"] = {"id": parent_id}
    return request(auth, "POST", f"{repo_base(ws, repo)}/{pr_id}/comments",
                   data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})


def _post_task(auth, ws, repo, pr_id, text, comment_id=None):
    payload = {"content": {"raw": text}}
    if comment_id is not None:
        payload["comment"] = {"id": comment_id}
    return request(auth, "POST", f"{repo_base(ws, repo)}/{pr_id}/tasks",
                   data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})


def _body(args):
    """Comment/task body from --text-file (preferred for rich markdown — no shell
    escaping) or --text."""
    if getattr(args, "text_file", None):
        with open(args.text_file, encoding="utf-8") as fh:
            return fh.read()
    if args.text is None:
        die("provide --text or --text-file")
    return args.text


def cmd_comment(args, auth, ws, repo):
    inline = None
    if args.file:
        inline = {"path": args.file}
        if args.old_line is not None:
            inline["from"] = args.old_line
        elif args.line is not None:
            inline["to"] = args.line
        else:
            die("--file needs --line N (new-side) or --old-line N (old-side)")
    elif args.line is not None or args.old_line is not None:
        die("--line/--old-line only make sense together with --file")
    text = _body(args)
    res = _post_comment(auth, ws, repo, args.id, text, inline=inline)
    where = f"{args.file}:{args.old_line or args.line}" if args.file else "general"
    print(f"posted comment {res.get('id')} ({where})")
    print(f"  {res.get('links', {}).get('html', {}).get('href', '')}")
    if args.task:
        t = _post_task(auth, ws, repo, args.id, text, comment_id=res.get("id"))
        print(f"  + created task {t.get('id')} on that comment")


def cmd_reply(args, auth, ws, repo):
    text = _body(args)
    res = _post_comment(auth, ws, repo, args.id, text, parent_id=int(args.comment_id))
    print(f"posted reply {res.get('id')} to comment {args.comment_id}")
    print(f"  {res.get('links', {}).get('html', {}).get('href', '')}")
    if args.task:
        t = _post_task(auth, ws, repo, args.id, text, comment_id=res.get("id"))
        print(f"  + created task {t.get('id')} on that reply")


def cmd_edit(args, auth, ws, repo):
    res = request(auth, "PUT", f"{repo_base(ws, repo)}/{args.id}/comments/{args.comment_id}",
                  data=json.dumps({"content": {"raw": _body(args)}}).encode(),
                  headers={"Content-Type": "application/json"})
    print(f"updated comment {args.comment_id} on #{args.id}")
    print(f"  {res.get('links', {}).get('html', {}).get('href', '')}")


def cmd_delete_comment(args, auth, ws, repo):
    request(auth, "DELETE", f"{repo_base(ws, repo)}/{args.id}/comments/{args.comment_id}")
    print(f"deleted comment {args.comment_id} on #{args.id}")


def cmd_resolve(args, auth, ws, repo, remove):
    method = "DELETE" if remove else "POST"
    request(auth, method, f"{repo_base(ws, repo)}/{args.id}/comments/{args.comment_id}/resolve")
    print(f"comment {args.comment_id} on #{args.id}: {'reopened' if remove else 'resolved'}")


def cmd_tasks(args, auth, ws, repo):
    items, _ = paginate(auth, f"{repo_base(ws, repo)}/{args.id}/tasks?pagelen=100")
    open_n = sum(1 for t in items if t.get("state") != "RESOLVED")
    for t in items:
        mark = "[x]" if t.get("state") == "RESOLVED" else "[ ]"
        on = (t.get("comment") or {}).get("id")
        loc = f"  (on comment {on})" if on else ""
        print(f"  {mark} #{t.get('id')} {truncate(t.get('content', {}).get('raw', ''), 100)}{loc}")
    print(f"\n  {len(items)} task(s) on #{args.id}, {open_n} open")


def cmd_task(args, auth, ws, repo):
    comment_id = int(args.on_comment) if args.on_comment else None
    t = _post_task(auth, ws, repo, args.id, _body(args), comment_id=comment_id)
    on = f" on comment {args.on_comment}" if args.on_comment else ""
    print(f"created task {t.get('id')}{on} ({t.get('state', 'UNRESOLVED')})")


def cmd_task_state(args, auth, ws, repo, state):
    t = request(auth, "PUT", f"{repo_base(ws, repo)}/{args.id}/tasks/{args.task_id}",
                data=json.dumps({"state": state}).encode(), headers={"Content-Type": "application/json"})
    print(f"task {args.task_id} on #{args.id}: {t.get('state', state)}")


def cmd_review_action(args, auth, ws, repo, endpoint, verb):
    method = "DELETE" if args.remove else "POST"
    res = request(auth, method, f"{repo_base(ws, repo)}/{args.id}/{endpoint}")
    if args.remove:
        print(f"removed your {verb} on #{args.id}")
    else:
        print(f"#{args.id}: your review state is now '{(res or {}).get('state', verb)}'")


# --- pipelines (needs the read:pipeline:bitbucket token scope) ---------------

def _encode_uuid(u):
    return "%7B" + u.strip().strip("{}") + "%7D"


def _pipe_state(obj):
    """Human 'STATE RESULT' from a pipeline/step state object."""
    st = obj.get("state", {})
    detail = (st.get("result") or {}).get("name") or (st.get("stage") or {}).get("name") or ""
    return f"{st.get('name', '?')} {detail}".strip()


def _pipes_base(ws, repo):
    return f"{API}/repositories/{ws}/{repo}/pipelines"


def cmd_pipelines(args, auth, ws, repo):
    ref = None
    if args.pr:
        ref = request(auth, "GET", f"{repo_base(ws, repo)}/{args.pr}").get("source", {}).get("branch", {}).get("name")
    elif args.branch:
        ref = args.branch
    params = {"sort": "-created_on", "pagelen": args.limit}
    if ref:
        params["q"] = f'target.ref_name="{ref}"'
    page = request(auth, "GET", f"{_pipes_base(ws, repo)}/?{urllib.parse.urlencode(params)}")
    vals = page.get("values", [])
    print(f"{len(vals)} recent pipeline(s){f' on {ref}' if ref else ''} in {ws}/{repo}:\n")
    for p in vals:
        target = p.get("target", {})
        commit = (target.get("commit") or {}).get("hash", "")[:8]
        print(f"  #{p.get('build_number'):<6} {_pipe_state(p):<22} {truncate(target.get('ref_name', '?'), 30):<30} "
              f"{commit}  {(p.get('created_on') or '')[:19].replace('T', ' ')}")


def cmd_pipeline(args, auth, ws, repo):
    p = request(auth, "GET", f"{_pipes_base(ws, repo)}/{args.id}")
    target = p.get("target", {})
    print(f"pipeline #{p.get('build_number')}  {_pipe_state(p)}")
    print(f"  branch: {target.get('ref_name', '?')}   commit: {(target.get('commit') or {}).get('hash', '')[:8]}")
    print(f"  link:   https://bitbucket.org/{ws}/{repo}/pipelines/results/{p.get('build_number')}")
    steps, _ = paginate(auth, f"{_pipes_base(ws, repo)}/{args.id}/steps/?pagelen=100")
    print(f"\n  steps ({len(steps)}) - use `pipeline-log {args.id} <n>` for a step's log:")
    for i, s in enumerate(steps, 1):
        print(f"    {i}. {_pipe_state(s):<22} {s.get('name', '(unnamed)')}   [{s.get('uuid', '').strip('{}')}]")


class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Step logs 302-redirect to a pre-signed S3 URL that carries its own auth in the
    query string. Re-sending our Basic auth header to S3 makes it reject the request
    (and echo the token), so drop all headers on the redirect."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(newurl)


def _fetch_step_log(auth, url):
    opener = urllib.request.build_opener(_StripAuthOnRedirect)
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    try:
        with opener.open(req) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        die(f"HTTP {e.code} fetching step log")
    except urllib.error.URLError as e:
        die(f"network error fetching step log: {e.reason}")


def cmd_pipeline_log(args, auth, ws, repo):
    uuid = args.step
    if args.step.isdigit():
        steps, _ = paginate(auth, f"{_pipes_base(ws, repo)}/{args.id}/steps/?pagelen=100")
        idx = int(args.step) - 1
        if not 0 <= idx < len(steps):
            die(f"step {args.step} out of range (1..{len(steps)})")
        uuid = steps[idx].get("uuid", "")
    log = _fetch_step_log(auth, f"{_pipes_base(ws, repo)}/{args.id}/steps/{_encode_uuid(uuid)}/log")
    lines = log.splitlines()
    if args.full or len(lines) <= args.tail:
        print(log)
    else:
        print(f"... [last {args.tail} of {len(lines)} lines; --full for all] ...")
        print("\n".join(lines[-args.tail:]))


# --- wiring -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Work with Bitbucket Cloud pull requests.")
    ap.add_argument("--workspace", default=os.environ.get("BITBUCKET_WORKSPACE"))
    ap.add_argument("--repo", default=os.environ.get("BITBUCKET_REPO"))
    ap.add_argument("--email", default=os.environ.get("BITBUCKET_EMAIL"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("configure", help="save email/token/workspace/repo/account-id (auto-detects account id)")
    p.add_argument("--email")
    p.add_argument("--token")
    p.add_argument("--workspace")
    p.add_argument("--repo")
    p.add_argument("--account-id", dest="account_id")

    p = sub.add_parser("list", help="list pull requests")
    p.add_argument("--state", default="OPEN", help="OPEN|MERGED|DECLINED|SUPERSEDED (default OPEN)")
    p.add_argument("--mine", action="store_true", help="only PRs you authored")
    p.add_argument("--review", action="store_true", help="only PRs where you are a reviewer")
    p.add_argument("--max-pages", type=int, default=6, help="page cap (50/page, default 6)")

    p = sub.add_parser("show", help="show a PR's details")
    p.add_argument("id")

    p = sub.add_parser("diff", help="print a PR's diff")
    p.add_argument("id")
    p.add_argument("--stat", action="store_true", help="show a diffstat instead of the full diff")

    p = sub.add_parser("comments", help="list a PR's comments")
    p.add_argument("id")

    p = sub.add_parser("comment", help="add a comment to a PR")
    p.add_argument("id")
    p.add_argument("--text", help="comment body (markdown)")
    p.add_argument("--text-file", dest="text_file", help="read the body from a file (best for rich markdown — avoids shell escaping)")
    p.add_argument("--file", help="path (repo-relative) for an inline comment")
    p.add_argument("--line", type=int, help="line in the NEW file version (with --file)")
    p.add_argument("--old-line", type=int, help="line in the OLD file version (with --file)")
    p.add_argument("--task", action="store_true", help="also create a task on the new comment")

    p = sub.add_parser("reply", help="reply to a comment (threaded)")
    p.add_argument("id")
    p.add_argument("comment_id", help="id of the comment to reply to")
    p.add_argument("--text", help="reply body (markdown)")
    p.add_argument("--text-file", dest="text_file", help="read the body from a file (best for rich markdown)")
    p.add_argument("--task", action="store_true", help="also create a task on the reply")

    p = sub.add_parser("edit", help="edit an existing comment")
    p.add_argument("id")
    p.add_argument("comment_id", help="id of the comment to edit")
    p.add_argument("--text", help="new body (markdown)")
    p.add_argument("--text-file", dest="text_file", help="read the new body from a file")

    p = sub.add_parser("delete-comment", help="delete a comment")
    p.add_argument("id")
    p.add_argument("comment_id", help="id of the comment to delete")

    for name, rm in (("resolve", False), ("unresolve", True)):
        p = sub.add_parser(name, help=f"{name} a comment thread")
        p.add_argument("id")
        p.add_argument("comment_id", help="id of the comment thread")
        p.set_defaults(_resolve_remove=rm)

    p = sub.add_parser("tasks", help="list a PR's tasks")
    p.add_argument("id")

    p = sub.add_parser("task", help="create a task on a PR (optionally attached to a comment)")
    p.add_argument("id")
    p.add_argument("--text", help="task body")
    p.add_argument("--text-file", dest="text_file", help="read the body from a file")
    p.add_argument("--on-comment", dest="on_comment", help="attach the task to this comment id")

    for name, state in (("task-done", "RESOLVED"), ("task-reopen", "UNRESOLVED")):
        p = sub.add_parser(name, help=f"mark a task {'resolved' if state == 'RESOLVED' else 'unresolved'}")
        p.add_argument("id")
        p.add_argument("task_id", help="task id")
        p.set_defaults(_task_state=state)

    for name, endpoint, verb in (
            ("approve", "approve", "approved"),
            ("request-changes", "request-changes", "changes_requested")):
        p = sub.add_parser(name, help=f"{name.replace('-', ' ')} a PR (use --remove to undo)")
        p.add_argument("id")
        p.add_argument("--remove", action="store_true", help="remove your previous " + name)
        p.set_defaults(_endpoint=endpoint, _verb=verb)

    p = sub.add_parser("pipelines", help="list recent pipelines (needs read:pipeline scope)")
    p.add_argument("--branch", help="filter to a branch")
    p.add_argument("--pr", help="pipelines for a PR's source branch")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("pipeline", help="show a pipeline and its steps")
    p.add_argument("id", help="pipeline build number or uuid")

    p = sub.add_parser("pipeline-log", help="print a pipeline step's log (to diagnose a failure)")
    p.add_argument("id", help="pipeline build number")
    p.add_argument("step", help="step number (from `pipeline`) or step uuid")
    p.add_argument("--tail", type=int, default=300, help="show the last N lines (default 300)")
    p.add_argument("--full", action="store_true", help="print the entire log")

    args = ap.parse_args()

    global CONFIG
    CONFIG = load_config()

    if args.cmd == "configure":
        cmd_configure(args)
        return

    token = cfg("BITBUCKET_API_TOKEN")
    if not token:
        die("no token — run `bitbucket_pr.py configure` (or set BITBUCKET_API_TOKEN)")
    email = cfg("BITBUCKET_EMAIL", args.email)
    if not email:
        die("no email — run `bitbucket_pr.py configure` (or set BITBUCKET_EMAIL)")
    ws = cfg("BITBUCKET_WORKSPACE", args.workspace)
    repo = cfg("BITBUCKET_REPO", args.repo)
    if not (ws and repo):
        d_ws, d_repo = detect_repo()
        ws, repo = ws or d_ws, repo or d_repo
    if not (ws and repo):
        die("set workspace/repo via `configure`, env, --workspace/--repo, or run inside a Bitbucket clone")
    auth = build_auth(email, token)

    dispatch = {
        "list": cmd_list, "show": cmd_show, "diff": cmd_diff,
        "comments": cmd_comments, "comment": cmd_comment, "reply": cmd_reply,
        "edit": cmd_edit, "delete-comment": cmd_delete_comment,
        "tasks": cmd_tasks, "task": cmd_task,
        "pipelines": cmd_pipelines, "pipeline": cmd_pipeline, "pipeline-log": cmd_pipeline_log,
    }
    if args.cmd in dispatch:
        dispatch[args.cmd](args, auth, ws, repo)
    elif args.cmd in ("resolve", "unresolve"):
        cmd_resolve(args, auth, ws, repo, args._resolve_remove)
    elif args.cmd in ("task-done", "task-reopen"):
        cmd_task_state(args, auth, ws, repo, args._task_state)
    else:  # approve / request-changes
        cmd_review_action(args, auth, ws, repo, args._endpoint, args._verb)


if __name__ == "__main__":
    main()
