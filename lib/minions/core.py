"""Core: paths, run state, config detection, git helpers."""
import dataclasses
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import unicodedata

HOME = os.path.expanduser("~")
MINION_HOME = os.path.join(HOME, ".minion")
RUNS_DIR = os.path.join(MINION_HOME, "runs")
WORKTREES_DIR = os.path.join(MINION_HOME, "worktrees")
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates")

CONFIG_NAME = ".minion.yaml"
SUMMARY_FILE = "summary.md"      # agent writes this into the run dir
COMMIT_FILE = "commit_msg.txt"   # agent may write this into the run dir


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str, maxlen: int = 32) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9あ-んア-ン一-龠a-z0-9]+", "-", text).strip("-")
    return (text[:maxlen].strip("-")) or "task"


# ---------------------------------------------------------------- subprocess

def sh(cmd: str, cwd: str | None = None, timeout: int = 600, env: dict | None = None):
    """Run a shell command. Returns (returncode, stdout+stderr)."""
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, env=e)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"[minion] TIMEOUT after {timeout}s: {cmd}"


def git(repo: str, *args: str, timeout: int = 120):
    return sh(" ".join(["git"] + [f"'{a}'" for a in args]), cwd=repo, timeout=timeout)


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# ---------------------------------------------------------------- run state

@dataclasses.dataclass
class Run:
    run_id: str
    task: str
    repo: str
    branch: str = ""
    worktree: str = ""
    state: str = "pending"
    ok: bool | None = None
    started: str = ""
    updated: str = ""
    events: list = dataclasses.field(default_factory=list)
    ci_round: int = 0
    test_round: int = 0
    pr_url: str = ""

    @property
    def dir(self) -> str:
        return os.path.join(RUNS_DIR, self.run_id)

    @property
    def transcript(self) -> str:
        return os.path.join(self.dir, "transcript.log")

    @property
    def summary_path(self) -> str:
        return os.path.join(self.dir, SUMMARY_FILE)

    @property
    def commit_msg_path(self) -> str:
        return os.path.join(self.dir, COMMIT_FILE)

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "status.json"), "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, run_id: str) -> "Run":
        with open(os.path.join(RUNS_DIR, run_id, "status.json"), encoding="utf-8") as f:
            return cls(**json.load(f))

    @classmethod
    def list_all(cls) -> list["Run"]:
        out = []
        if os.path.isdir(RUNS_DIR):
            for name in sorted(os.listdir(RUNS_DIR), reverse=True):
                p = os.path.join(RUNS_DIR, name, "status.json")
                if os.path.exists(p):
                    try:
                        out.append(cls.load(name))
                    except Exception:
                        pass
        return out

    def log(self, msg: str):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.transcript, "a", encoding="utf-8") as f:
            f.write(msg.rstrip("\n") + "\n")

    def event(self, state: str, detail: str = "", ok: bool = True):
        self.state = state
        self.ok = ok if state in ("failed", "done") else self.ok
        self.updated = now_iso()
        self.events.append({"t": now_iso(), "state": state, "detail": detail[:400], "ok": ok})
        self.save()
        kind = "AGENT" if state.startswith(("implement", "fix")) else "DET  "
        self.log(f"\n=== [{self.run_id}] {kind} {state} === {detail[:200]}")

    def fail(self, state: str, detail: str):
        self.event(state, detail, ok=False)
        self.state = "failed"
        self.ok = False
        self.save()
        self.log(f"!!! RUN FAILED at {state}: {detail[:500]}")


# ---------------------------------------------------------------- config

DEFAULT_CONFIG = """\
# minion 設定 — `minion init` が自動検出して生成します
lint:
  fix: {fix}       # 自動修正コマンド (決定的ノードで実行)
  check: {check}   # 検査のみのコマンド
test: {test}       # ローカルテスト (決定的ノード)
ci: {ci}           # "CI相当" のローカル実行コマンド (未設定なら test を流用)
pr_base: {pr_base} # PR のベースブランチ
goose_args: []     # goose run に追加で渡す引数 (例: --with-builtin ...)
"""


def detect_config(repo: str) -> str:
    fix, check, test, base = "[]", "[]", "null", "main"
    pj = os.path.join(repo, "package.json")
    if os.path.exists(pj):
        try:
            scripts = json.load(open(pj)).get("scripts", {})
            fix = "['npx prettier --write .']" if shutil.which("npx") else "[]"
            test = f"'npm test'" if "test" in scripts else "null"
        except Exception:
            pass
    elif os.path.exists(os.path.join(repo, "pyproject.toml")):
        fix = "[]" if not have("ruff") else "['ruff check --fix .', 'ruff format .']"
        test = "'python3 -m pytest -q'" if have("pytest") or os.path.exists(os.path.join(repo, "tests")) else "null"
    elif os.path.exists(os.path.join(repo, "Cargo.toml")):
        fix, test = "['cargo fmt']", "'cargo test'"
    elif os.path.exists(os.path.join(repo, "go.mod")):
        fix, test = "['gofmt -w .']", "'go test ./...'"
    elif os.path.exists(os.path.join(repo, "Makefile")):
        fix, test = "[]", "'make test'"
    rc, out = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.strip():
        base = out.strip().replace("origin/", "")
    rc, out = git(repo, "branch", "--list", "main", "master")
    if rc == 0 and "master" in out and "main" not in out:
        base = "master"
    return DEFAULT_CONFIG.format(fix=fix, check=check, test=test,
                                 ci="null", pr_base=f"'{base}'")


def load_yaml_simple(path: str) -> dict:
    """Minimal YAML subset parser (nested one level + inline lists). No deps."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    except ImportError:
        pass
    data: dict = {}
    section = None
    for raw in open(path, encoding="utf-8"):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            section = line[:-1].strip()
            data[section] = {}
        elif line.startswith(" ") and section and ":" in line:
            k, _, v = line.strip().partition(":")
            v = v.strip()
            data[section][k] = _coerce(v)
        elif ":" in line:
            k, _, v = line.partition(":")
            data[k.strip()] = _coerce(v.strip())
            section = None
    return data


def _coerce(v: str):
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_coerce(x.strip().strip("'\"")) for x in inner.split(",") if x.strip()]
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    if v in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v in ("true", "false"):
        return v == "true"
    return v


def read_config(repo: str) -> dict:
    p = os.path.join(repo, CONFIG_NAME)
    cfg = load_yaml_simple(p) if os.path.exists(p) else {}
    lint = cfg.get("lint") or {}
    cfg["fix_cmds"] = [c for c in (lint.get("fix") or []) if c]
    cfg["check_cmds"] = [c for c in (lint.get("check") or []) if c]
    cfg["test_cmd"] = cfg.get("test")
    cfg["ci_cmd"] = cfg.get("ci") or cfg.get("test")
    cfg["pr_base"] = cfg.get("pr_base") or "main"
    cfg["goose_args"] = cfg.get("goose_args") or []
    return cfg
