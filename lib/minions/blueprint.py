"""Blueprint: state machine mixing deterministic nodes with goose agent nodes.

  setup → hydrate → implement(AGENT) → lint → test ⇄ fix_tests(AGENT)
        → commit → push → ci ⇄ fix_ci(AGENT) → pr → done
"""
import glob
import os
import shlex

from . import core
from .core import Run, git, sh, now_iso

MAX_TEST_AGENT_ROUNDS = 2   # agent によるテスト修正は合計2回まで
MAX_CI_ROUNDS = 2           # Stripe流: CI は「多くとも2周」

AGENT_PREAMBLE = (
    "あなたは無人実行されるコーディングエージェント (minion) です。"
    "人間への質問はできません。現在のディレクトリは隔離された git worktree です。"
    "git の commit/push/branch 操作は禁止です (オーケストレータが決定的に行います)。"
    "AGENTS.md などのルールファイルがあれば必ず最初に読んで従ってください。"
)


def _goose(run: Run, prompt: str, cfg: dict, max_turns: int = 60, timeout: int = 2400):
    """Run one goose agent node inside the worktree. Returns (ok, output)."""
    args = " ".join(shlex.quote(a) for a in cfg.get("goose_args", []))
    cmd = (
        f"goose run --no-session --max-turns {max_turns} "
        f"--max-tool-repetitions 8 {args} "
        f"--system {shlex.quote(AGENT_PREAMBLE)} "
        f"--text {shlex.quote(prompt)}"
    )
    run.log(f"\n$ {cmd[:300]}")
    rc, out = sh(cmd, cwd=run.worktree, timeout=timeout,
                 env={"GOOSE_MODE": "auto"})
    run.log(out)
    return rc == 0, out


# ------------------------------------------------------------- deterministic

def node_setup(run: Run, cfg: dict) -> str:
    repo = run.repo
    for d in (core.RUNS_DIR, core.WORKTREES_DIR):
        os.makedirs(d, exist_ok=True)
    rc, out = git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        return f"not a git repo: {out.strip()}"
    run.repo = out.strip()
    rc, out = git(run.repo, "status", "--porcelain")
    if rc == 0 and out.strip() and False:  # worktree なので元repoの汚れは無視
        pass
    wt = os.path.join(core.WORKTREES_DIR, f"{os.path.basename(run.repo)}-{run.run_id}")
    rc, out = git(run.repo, "worktree", "add", "-b", run.branch, wt, "HEAD")
    if rc != 0:
        return f"worktree add failed: {out.strip()}"
    run.worktree = wt
    run.event("setup", f"worktree={wt} branch={run.branch}")
    return ""


def node_hydrate(run: Run, cfg: dict) -> str:
    """決定的コンテキスト収集: ルールファイル一覧・差分ヒントをプロンプト用にまとめる。"""
    lines = [f"# task: {run.task}",
             f"# repo: {run.repo}  base branch: {cfg.get('pr_base')}"]
    rules = sorted(glob.glob(os.path.join(run.worktree, "**", "AGENTS.md"), recursive=True)
                   + glob.glob(os.path.join(run.worktree, "**", ".cursorrules"), recursive=True))
    rules = [r for r in rules if "/node_modules/" not in r][:20]
    if rules:
        lines.append("# rule files (READ FIRST): " + ", ".join(
            os.path.relpath(r, run.worktree) for r in rules))
    rc, out = git(run.repo, "log", "--oneline", "-5")
    if rc == 0:
        lines.append("# recent commits:\n" + out.strip())
    lines.append(f"# 変更概要はこの絶対パスに書いてください: {run.summary_path}")
    lines.append(f"# コミットメッセージ案 (1行) はここに: {run.commit_msg_path}")
    open(os.path.join(run.dir, "prompt_context.md"), "w", encoding="utf-8").write("\n".join(lines))
    run.event("hydrate", f"rules={len(rules)}")
    return ""


def node_implement(run: Run, cfg: dict) -> str:
    ctx = open(os.path.join(run.dir, "prompt_context.md"), encoding="utf-8").read()
    prompt = f"""{ctx}

## 指示
上のタスクをこのリポジトリで完遂してください (one-shot)。
- まずルールファイルを読み、規約に従うこと
- 実装・ドキュメント・必要ならテスト追加まで行う
- 可能ならローカルでlint/テストを実行して自己検証すること
- 完了後、必ず {run.summary_path} に変更概要 (Markdown) を、
  {run.commit_msg_path} にコミットメッセージ案 (1行, Conventional Commits) を書くこと
- git commit / push はしないこと"""
    ok, _ = _goose(run, prompt, cfg)
    run.event("implement", "agent finished", ok=ok)
    return "" if ok else "implement agent failed (see transcript)"


def node_lint(run: Run, cfg: dict) -> str:
    """決定的ノード: 自動修正を最大3周 (Stripe流の shift-left)。"""
    fixes = cfg.get("fix_cmds") or []
    if not fixes:
        run.event("lint", "no fix commands configured")
        return ""
    for i in range(3):
        changed = False
        for c in fixes:
            rc, out = sh(c, cwd=run.worktree, timeout=300)
            run.log(f"\n$ {c}\n{out[-2000:]}")
            if rc != 0:
                run.event("lint", f"fix cmd failed: {c}", ok=False)
                return f"lint fix failed: {c}"
            _, diff = git(run.worktree, "status", "--porcelain")
            if diff.strip():
                changed = True
        _, diff = git(run.worktree, "status", "--porcelain")
        if not diff.strip():
            break
        if not changed:
            break
    for c in cfg.get("check_cmds") or []:
        rc, out = sh(c, cwd=run.worktree, timeout=300)
        run.log(f"\n$ {c}\n{out[-2000:]}")
        if rc != 0:
            run.event("lint", f"check failed: {c}", ok=False)
            return f"lint check failed: {c}"
    run.event("lint", "ok")
    return ""


def run_tests(run: Run, cfg: dict) -> tuple[bool, str]:
    cmd = cfg.get("test_cmd")
    if not cmd:
        run.event("test", "no test command configured — skip")
        return True, ""
    rc, out = sh(cmd, cwd=run.worktree, timeout=1800)
    run.log(f"\n$ {cmd}\n{out[-6000:]}")
    return rc == 0, out


def node_test(run: Run, cfg: dict) -> str:
    ok, out = run_tests(run, cfg)
    if ok:
        run.event("test", "passed")
        return ""
    run.event("test", "FAILED", ok=False)
    return "tests failed"


def node_fix(run: Run, cfg: dict, kind: str, out: str) -> str:
    """AGENT ノード: テスト/CI 失敗の出力を食わせてローカルで修正させる。"""
    prompt = f"""以下の {kind} が失敗しています。原因を特定し、この worktree で修正してください。
修正後、可能なら {cfg.get('test_cmd') or 'tests'} を実行して通ることを確認してください。
git commit / push はしないこと。完了したら {run.summary_path} に追記してください。

## 失敗ログ (末尾)
```
{out[-8000:]}
```"""
    ok, _ = _goose(run, prompt, cfg, max_turns=40)
    run.event(f"fix_{kind}", f"round finished", ok=ok)
    return "" if ok else f"fix_{kind} agent failed"


def node_commit(run: Run, cfg: dict) -> str:
    _, diff = git(run.worktree, "status", "--porcelain")
    if not diff.strip():
        return "no changes produced by agent"
    git(run.worktree, "add", "-A")
    msg = "minion: " + run.task.splitlines()[0][:70]
    if os.path.exists(run.commit_msg_path):
        first = open(run.commit_msg_path, encoding="utf-8").read().strip().splitlines()
        if first and first[0].strip():
            msg = first[0].strip()
    body = f"\n\nTask: {run.task}\nRun: {run.run_id}\n(goose minion)"
    rc, out = git(run.worktree, "commit", "-m", msg + body)
    if rc != 0:
        return f"commit failed: {out.strip()}"
    run.event("commit", msg)
    return ""


def node_push(run: Run, cfg: dict) -> str:
    rc, out = git(run.repo, "remote", "get-url", "origin")
    if rc != 0:
        run.event("push", "no origin remote — local branch only")
        run.state = "done_local"
        run.save()
        return "STOP_LOCAL"
    rc, out = git(run.worktree, "push", "-u", "origin", run.branch)
    run.log(f"\n$ git push\n{out[-2000:]}")
    if rc != 0:
        return f"push failed: {out.strip()}"
    run.event("push", run.branch)
    return ""


def node_ci(run: Run, cfg: dict) -> str:
    """CI周: ローカルでCI相当コマンド。gh があれば GitHub Actions も監視 (best effort)。"""
    run.ci_round += 1
    cmd = cfg.get("ci_cmd")
    if cmd:
        rc, out = sh(cmd, cwd=run.worktree, timeout=1800)
        run.log(f"\n[CI round {run.ci_round}] $ {cmd}\n{out[-6000:]}")
        if rc == 0:
            run.event("ci", f"round {run.ci_round} passed")
            return ""
        run.event("ci", f"round {run.ci_round} FAILED", ok=False)
        return "ci failed"
    # GitHub Actions 監視 (設定なしの場合のフォールバック)
    if core.have("gh"):
        rc, _ = sh(f"gh run list --branch {run.branch} --limit 1 --json databaseId -q '.[0].databaseId'",
                   cwd=run.worktree, timeout=60)
        if rc == 0:
            rid = _.strip()
            if rid:
                rc, out = sh(f"gh run watch {rid} --exit-status", cwd=run.worktree, timeout=2400)
                run.log(f"\n[CI round {run.ci_round}] gh run watch {rid}\n{out[-3000:]}")
                if rc == 0:
                    run.event("ci", f"round {run.ci_round} passed (Actions)")
                    return ""
                run.event("ci", f"round {run.ci_round} FAILED (Actions)", ok=False)
                return "ci failed (Actions)"
    run.event("ci", "no CI configured — skip")
    return ""


def node_pr(run: Run, cfg: dict) -> str:
    if not core.have("gh"):
        run.event("pr", "gh not installed — branch pushed, PR skipped")
        return ""
    rc, out = git(run.repo, "remote", "get-url", "origin")
    if rc != 0:
        return ""
    if "github.com" not in out:
        run.event("pr", "origin is not GitHub — PR skipped")
        return ""
    body = ""
    if os.path.exists(run.summary_path):
        body = open(run.summary_path, encoding="utf-8").read()[:4000]
    else:
        _, body = git(run.worktree, "log", "-1", "--stat")
    _, logmsg = git(run.worktree, "log", "-1", "--pretty=%s")
    title = logmsg.strip() or f"minion: {run.task[:60]}"
    rc, out = sh(
        f"gh pr create --title {shlex.quote(title)} --body {shlex.quote(body)} "
        f"--base {shlex.quote(str(cfg.get('pr_base')))} --head {shlex.quote(run.branch)}",
        cwd=run.worktree, timeout=120)
    run.log(f"\n$ gh pr create\n{out[-2000:]}")
    if rc == 0 and out.strip().startswith("http"):
        run.pr_url = out.strip().splitlines()[-1]
        run.event("pr", run.pr_url)
        return ""
    run.event("pr", f"gh pr create failed: {out.strip()[:200]}", ok=False)
    return ""


# ------------------------------------------------------------- orchestration

def execute(run: Run, cfg: dict):
    run.started = now_iso()
    run.event("pending", f"task={run.task[:120]}")
    err = node_setup(run, cfg)
    if err:
        return run.fail("setup", err)
    err = node_hydrate(run, cfg) or node_implement(run, cfg) or node_lint(run, cfg)
    if err:
        return run.fail(err.split()[0] if err else "?", err)

    # test ⇄ fix_tests ループ (agent 修正は最大2回)
    while True:
        err = node_test(run, cfg)
        if not err:
            break
        if run.test_round >= MAX_TEST_AGENT_ROUNDS:
            return run.fail("test", "tests still failing after max fix rounds")
        run.test_round += 1
        ok, out = run_tests_quiet(run, cfg)
        err2 = node_fix(run, cfg, "tests", out)
        if err2:
            return run.fail("fix_tests", err2)

    err = node_commit(run, cfg)
    if err:
        return run.fail("commit", err)
    err = node_push(run, cfg)
    if err == "STOP_LOCAL":
        run.event("done", "completed locally (no remote)")
        run.ok = True
        run.save()
        _, patch = git(run.worktree, "diff", f"{cfg.get('pr_base')}...HEAD")
        open(os.path.join(run.dir, "changes.patch"), "w").write(patch)
        return
    if err:
        return run.fail("push", err)

    # ci ⇄ fix_ci ループ (CI は最大2周)
    while True:
        err = node_ci(run, cfg)
        if not err:
            break
        if run.ci_round >= MAX_CI_ROUNDS:
            return run.fail("ci", f"CI failed after {run.ci_round} rounds — human review needed")
        ok, out = run_ci_quiet(run, cfg)
        err2 = node_fix(run, cfg, "ci", out)
        if err2:
            return run.fail("fix_ci", err2)
        rc, out2 = node_push_quiet(run)
        if rc != 0:
            return run.fail("push", out2)

    err = node_pr(run, cfg)
    if err:
        run.log(f"[pr] {err}")
    run.event("done", f"branch={run.branch} pr={run.pr_url or '-'}", ok=True)
    run.ok = True
    run.save()
    _, patch = git(run.worktree, "diff", f"{cfg.get('pr_base')}...HEAD")
    open(os.path.join(run.dir, "changes.patch"), "w").write(patch)


def run_tests_quiet(run: Run, cfg: dict) -> tuple[bool, str]:
    cmd = cfg.get("test_cmd") or "true"
    return sh(cmd, cwd=run.worktree, timeout=1800)


def run_ci_quiet(run: Run, cfg: dict) -> tuple[bool, str]:
    cmd = cfg.get("ci_cmd") or cfg.get("test_cmd") or "true"
    return sh(cmd, cwd=run.worktree, timeout=1800)


def node_push_quiet(run: Run) -> tuple[int, str]:
    return git(run.worktree, "push", "origin", run.branch)
