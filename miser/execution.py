"""Supervised, allowlisted command execution.

This is deliberately *not* a shell. The model may only ask the host to run a
command whose leading argv tokens match an explicit allowlist prefix; the host
then resolves the binary itself, asks the user for approval, and runs the
result without a shell. App-level guards are not an OS sandbox.
"""

import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

# Anything that would let one argv entry express shell syntax. Rejecting these
# keeps the tool a real argv exec even if a caller later decides to use a shell.
SHELL_METACHARACTERS = ";&|<>$`\n\r()"

PYTHON_NAMES = {"python", "python3", "py"}

# Prefix rules. A command matches when its argv starts with one of these tuples.
DEFAULT_ALLOWLIST = (
    ("python3", "-m", "unittest"),
    ("python3", "-m", "pytest"),
    ("python3", "-m", "mypy"),
    ("pytest",),
    ("ruff",),
    ("mypy",),
    ("node", "--test"),
    ("git", "status"),
    ("git", "diff"),
)

SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "SYSTEMROOT"}

MAX_ARGV = 32
MAX_ARG_LENGTH = 500
OUTPUT_CAP = 8000
MAX_JOBS = 8


def format_command(argv):
    """Display form for logs and approval prompts. Never executed."""
    return shlex.join(list(argv))


def sanitised_env():
    """Child commands do not need gateway or search credentials. Not a sandbox."""
    env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def wait_for_process(process, timeout, cancelled=None):
    """Poll cancellable UI work; a plain CLI keeps subprocess's ordinary wait."""
    if cancelled is None:
        return process.wait(timeout=timeout)
    deadline = time.monotonic() + timeout
    while True:
        if cancelled():
            raise KeyboardInterrupt
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue


def _normalise_program(name):
    """Map a python alias to the canonical allowlist token."""
    base = os.path.basename(str(name)).lower()
    if base in PYTHON_NAMES or base.startswith("python3."):
        return "python3"
    return base


def check_argv(argv, allowlist=None):
    """Validate argv shape and return it unchanged, or raise ValueError."""
    if not isinstance(argv, list) or not argv:
        raise ValueError("run_command requires a nonempty argv array")
    if len(argv) > MAX_ARGV:
        raise ValueError(f"run_command accepts at most {MAX_ARGV} argv entries")
    for index, item in enumerate(argv):
        if not isinstance(item, str):
            raise ValueError(f"argv[{index}] must be a string")
        if not item:
            raise ValueError(f"argv[{index}] must not be empty")
        if len(item) > MAX_ARG_LENGTH:
            raise ValueError(f"argv[{index}] exceeds {MAX_ARG_LENGTH} characters")
        bad = sorted({character for character in item if character in SHELL_METACHARACTERS})
        if bad:
            shown = " ".join(repr(character) for character in bad)
            raise ValueError(
                f"Shell metacharacter(s) {shown} are not allowed; pass argv entries literally")
    if "/" in argv[0] or "\\" in argv[0]:
        raise ValueError("Executable must be an allowlisted program name, not a path")
    rules = DEFAULT_ALLOWLIST if allowlist is None else tuple(tuple(rule) for rule in allowlist)
    normalised = [_normalise_program(argv[0])] + list(argv[1:])
    for rule in rules:
        if tuple(normalised[:len(rule)]) == tuple(rule):
            return list(argv)
    allowed = ", ".join(format_command(rule) for rule in rules) or "(none configured)"
    raise ValueError(
        f"Command is not on the allowlist ({format_command(argv)}). Allowed prefixes: {allowed}")


class CommandSupervisor:
    """Run allowlisted, host-approved commands; manage background jobs."""

    def __init__(self, workspace, ledger, approval_callback=None, allowlist=None,
                 timeout=120, max_runs=10, max_jobs=MAX_JOBS):
        self.workspace = workspace
        self.ledger = ledger
        self.approval_callback = approval_callback
        self.allowlist = tuple(tuple(rule) for rule in (
            DEFAULT_ALLOWLIST if allowlist is None else allowlist))
        self.timeout = max(1, int(timeout))
        self.max_runs = max(1, int(max_runs))
        self.max_jobs = max(1, int(max_jobs))
        self.runs = 0
        self.jobs = {}
        self.cancelled = None
        self.jobs_dir = os.path.join(str(self.workspace.root), ".miser", "jobs")

    # -- helpers -----------------------------------------------------------

    def _resolve(self, program):
        """Resolve the executable ourselves; never let argv[0] pick a path."""
        if _normalise_program(program) == "python3":
            return sys.executable
        resolved = shutil.which(os.path.basename(program))
        if not resolved:
            raise ValueError(f"Command not found on PATH: {program}")
        return resolved

    def _approve(self, argv, display):
        if self.approval_callback is None:
            raise ValueError(
                "No approval channel is available, so commands cannot run in this mode")
        answer = self.approval_callback(display)
        if not answer:
            raise ValueError("Command rejected by user")

    def _read_log(self, path):
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as handle:
                handle.seek(max(0, size - OUTPUT_CAP))
                return handle.read(OUTPUT_CAP).decode("utf-8", errors="replace"), size > OUTPUT_CAP
        except OSError:
            return "", False

    @staticmethod
    def _terminate(process):
        """Stop the command, and its process group where the host supports it."""
        killpg = getattr(os, "killpg", None)
        if killpg is not None:
            try:
                # start_new_session makes pid the group id, even after its leader exits.
                killpg(process.pid, signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            process.kill()
        except ProcessLookupError:
            pass

    # -- actions -----------------------------------------------------------

    def run(self, argv, background=False):
        argv = check_argv(argv, self.allowlist)
        display = format_command(argv)
        if self.runs >= self.max_runs:
            raise ValueError(f"Command-run limit reached ({self.max_runs} per task)")
        resolved = self._resolve(argv[0])
        self._approve(argv, display)
        self.runs += 1
        started = time.monotonic()
        if background:
            return self._run_background(argv, resolved, display, started)

        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([resolved] + list(argv[1:]), cwd=self.workspace.root,
                                       env=sanitised_env(), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       **({"start_new_session": True} if os.name == "posix" else {}))
            timed_out = False
            try:
                wait_for_process(process, self.timeout, self.cancelled)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate(process)
                process.wait()
            except BaseException:
                self._terminate(process)
                process.wait()
                raise
            # A successful group leader can still leave children holding the log.
            if not timed_out:
                self._terminate(process)
            size = output.tell()
            output.seek(max(0, size - OUTPUT_CAP))
            text = output.read(OUTPUT_CAP).decode("utf-8", errors="replace")
        result = {"command": display, "argv": list(argv), "exit_code": process.returncode,
                  "timed_out": timed_out, "output": text, "output_truncated": size > OUTPUT_CAP,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        self.ledger.record("command", command=display, background=False,
                           exit_code=process.returncode, timed_out=timed_out)
        return result

    def _run_background(self, argv, resolved, display, started):
        active = [job for job in self.jobs.values() if job["process"].poll() is None]
        if len(active) >= self.max_jobs:
            raise ValueError(f"Background job limit reached ({self.max_jobs} running)")
        os.makedirs(self.jobs_dir, exist_ok=True)
        job_id = uuid.uuid4().hex[:8]
        log_path = os.path.join(self.jobs_dir, job_id + ".log")
        spawn = {"start_new_session": True} if os.name == "posix" else {}
        with open(log_path, "wb") as log:
            process = subprocess.Popen([resolved] + list(argv[1:]), cwd=self.workspace.root,
                                       env=sanitised_env(), stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, **spawn)
        self.jobs[job_id] = {"process": process, "log": log_path, "command": display,
                         "started": started}
        self.ledger.record("command", command=display, background=True, job_id=job_id)
        return {"job_id": job_id, "command": display, "running": process.poll() is None,
                "exit_code": process.poll(), "log": log_path,
                "hint": "Call run_command with action=status and this job_id for output."}

    def status(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job id: {job_id}")
        output, truncated = self._read_log(job["log"])
        code = job["process"].poll()
        return {"job_id": job_id, "running": code is None, "exit_code": code,
                "command": job["command"], "output": output, "output_truncated": truncated,
                "elapsed_seconds": round(time.monotonic() - job["started"], 3)}

    def stop(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job id: {job_id}")
        self._terminate(job["process"])
        job["process"].wait()
        output, truncated = self._read_log(job["log"])
        self.ledger.record("command", command=job["command"], background=True,
                           exit_code=job["process"].returncode, stopped=True)
        return {"job_id": job_id, "running": False, "exit_code": job["process"].returncode,
                "command": job["command"], "output": output, "output_truncated": truncated}

    def close(self):
        """Reap this task's jobs when it ends, including on interruption."""
        for job in self.jobs.values():
            self._terminate(job["process"])
            job["process"].wait()

    def invoke(self, arguments):
        """Entry point used by ToolRunner for the run_command tool."""
        action = str(arguments.get("action") or "run")
        if action == "run":
            argv = check_argv(arguments.get("argv"), self.allowlist)
            return self.run(argv, background=bool(arguments.get("background")))
        if action in {"status", "stop"}:
            job_id = str(arguments.get("job_id") or "").strip()
            if not job_id:
                raise ValueError(f"run_command action={action} requires job_id")
            return (self.status if action == "status" else self.stop)(job_id)
        raise ValueError("run_command action must be run, status, or stop")
