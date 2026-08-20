"""CLI entry: minion init|run|list|log|show|clean|doctor|dashboard"""
import argparse
import os
import subprocess
import sys
import time

from . import core, blueprint
from .core import Run, git, sh, now_iso, slugify

STATE_ICONS = {"pending": "…", "failed": "✗", "done": "✓", "done_local": "✓"}


def env_path(libdir):
    return os.environ.get("PYTHONPATH", "")


def cmd_init(args):
    repo = os.path.abspath(args.repo)
    if not os.path.exists(os.path.join(repo, ".git")):
        return print(f"error: {repo} is not a git repository")
    made = []
    agents = os.path.join(repo, "AGENTS.md")
    if not os.path.exists(agents):
        tpl = open(os.path.join(core.TEMPLATES_DIR, "AGENTS.md"), encoding="utf-8").read()
        open(agents, "w", encoding="utf-8").write(tpl)
        made.append("AGENTS.md")
    claude = os.path.join(repo, "CLAUDE.md")
    if not os.path.exists(claude):
        os.symlink("AGENTS.md", claude)
        made.append("CLAUDE.md -> AGENTS.md (全エージェントでルール共有)")
    cfg = os.path.join(repo, core.CONFIG_NAME)
    if not os.path.exists(cfg):
        open(cfg, "w", encoding="utf-8").write(core.detect_config(repo))
        made.append(core.CONFIG_NAME + " (自動検出 — 要調整)")
    print("minion init 完了:")
    for m in made:
        print(f"  + {m}")
    if not made:
        print("  (すべて設定済み)")


def cmd_run(args):
    task = args.task if args.task else sys.stdin.read().strip()
    if not task:
        return print("error: task description required")
    repo = os.path.abspath(args.repo)
    cfg = core.read_config(repo)
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + slugify(task)
    run = Run(run_id=run_id, task=task, repo=repo, started=now_iso(),
              branch=f"minion/{run_id}")
    os.makedirs(run.dir, exist_ok=True)
    run.save()
    print(f"▶ minion run  {run_id}\n  repo: {repo}\n  task: {task[:100]}")
    if args.detach:
        libdir = os.path.dirname(os.path.dirname(os.path.abspath(core.__file__)))
        import subprocess as sp
        env = dict(os.environ)
        env["PYTHONPATH"] = libdir + os.pathsep + env.get("PYTHONPATH", "")
        sp.Popen([sys.executable, "-m", "minions.cli", "run", "--repo", repo, task],
                 stdout=open(run.transcript, "a"), stderr=sp.STDOUT,
                 start_new_session=True, env=env)
        print("  (バックグラウンドで実行中 — `minion list` で確認)")
        return
    blueprint.execute(run, cfg)
    print(f"\n{STATE_ICONS.get(run.state,'?')} state={run.state}  "
          f"branch={run.branch}  pr={run.pr_url or '-'}")
    print(f"  log: minion log {run_id}")
    sys.exit(0 if run.ok else 1)


def cmd_list(args):
    runs = Run.list_all()
    if not runs:
        return print("no runs yet — try: minion run \"タスク\"")
    print(f"{'RUN_ID':<24} {'STATE':<10} {'BRANCH':<40} PR/DETAIL")
    for r in runs[:args.n]:
        detail = r.pr_url or (r.events[-1]["detail"][:40] if r.events else "")
        print(f"{r.run_id:<24} {STATE_ICONS.get(r.state,'?')+' '+r.state:<10} "
              f"{r.branch:<40} {detail[:60]}")


def cmd_log(args):
    runs = Run.list_all()
    rid = args.run_id or (runs[0].run_id if runs else "")
    if not rid:
        return print("no runs")
    path = os.path.join(core.RUNS_DIR, rid, "transcript.log")
    if args.follow:
        os.execvp("tail", ["tail", "-n", "100", "-f", path])
    os.system(f"cat '{path}' 2>/dev/null | tail -n {args.n}")


def cmd_show(args):
    r = Run.load(args.run_id)
    print(f"run:    {r.run_id}\ntask:   {r.task}\nrepo:   {r.repo}")
    print(f"branch: {r.branch}\nstate:  {r.state}\nworktree: {r.worktree}")
    if r.pr_url:
        print(f"pr:     {r.pr_url}")
    print("\ntimeline:")
    for e in r.events:
        mark = "✓" if e["ok"] else "✗"
        print(f"  {e['t']}  {mark} {e['state']:<12} {e['detail'][:80]}")
    s = r.summary_path
    if os.path.exists(s) and args.summary:
        print("\n--- summary.md ---\n" + open(s, encoding="utf-8").read())


def cmd_clean(args):
    n = 0
    for r in Run.list_all():
        if args.all or r.state in ("done", "done_local", "failed"):
            if r.worktree and os.path.exists(r.worktree):
                git(r.repo, "worktree", "remove", "--force", r.worktree)
                n += 1
    git(os.path.expanduser("~"), "worktree", "prune") if False else None
    print(f"removed {n} worktrees")


def cmd_doctor(args):
    checks = [("goose", "エージェントコア (Stripe Minions と同じ基盤)"),
              ("git", "バージョン管理 / worktree 分離"),
              ("gh", "GitHub PR 作成 (任意)"),
              ("python3", "minion CLI 自身")]
    print("minion doctor\n-------------")
    for c, why in checks:
        ok = core.have(c)
        rc, ver = sh(f"{c} --version") if ok else (1, "")
        print(f"  {'✓' if ok else '✗'} {c:<9} {ver.strip()[:40] or 'MISSING':<42} {why}")
    provider = os.environ.get("GOOSE_PROVIDER", "")
    print(f"\n  goose provider: {provider or '(config.yaml の active_provider を使用)'}")


def main():
    p = argparse.ArgumentParser(prog="minion",
                                 description="personal one-shot coding agents (goose-powered, Stripe Minions inspired)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="対象リポジトリに AGENTS.md / CLAUDE.md / .minion.yaml を生成")
    s.add_argument("--repo", default=".")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="minion をワンショット実行")
    s.add_argument("--repo", default=".")
    s.add_argument("--detach", "-d", action="store_true", help="バックグラウンド実行 (並列化用)")
    s.add_argument("task", nargs="?", help="タスク description")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("list", help="実行一覧")
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("log", help="transcript 表示")
    s.add_argument("run_id", nargs="?")
    s.add_argument("-f", "--follow", action="store_true")
    s.add_argument("-n", type=int, default=200)
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("show", help="run 詳細 + タイムライン")
    s.add_argument("run_id")
    s.add_argument("--summary", action="store_true")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("clean", help="完了済み run の worktree を削除")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_clean)

    s = sub.add_parser("doctor", help="依存チェック")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("dashboard", help="ローカル Web UI (run 管理)")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=lambda a: __import__("minions.dashboard", fromlist=["serve"]).serve(a.port))

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
