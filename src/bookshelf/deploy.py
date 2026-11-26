"""Did the website actually update? Follows the GitHub Actions run for a commit with `gh`.

`bookshelf publish` pushes, and GitHub's "Test and publish site" workflow then tests and deploys.
A push can succeed while the deploy fails (it did on 2026-11-25), leaving the old site up, so
publish waits for the run and says how it ended. Everything here goes through the GitHub CLI
(`gh`); without it, or when it isn't logged in, the check is skipped with a note.
"""

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

WORKFLOW = "pages.yml"
TEXT = {"capture_output": True, "encoding": "utf-8", "errors": "replace"}

# A Runner runs one gh command in the repository: gh(["run", "list", ...]) -> CompletedProcess
Runner = Callable[[list[str]], subprocess.CompletedProcess]


def gh_runner(repo: Path) -> Runner | None:
    """The real gh, or None if it isn't installed."""
    exe = shutil.which("gh")
    if exe is None:
        return None
    return lambda args: subprocess.run([exe, *args], cwd=repo, check=False, **TEXT)


@dataclass
class Outcome:
    state: str  # "live", "failed", "cancelled", "waiting" (gave up waiting) or "unknown"
    run_id: int | None = None
    url: str | None = None  # the run's page on GitHub
    failed_steps: list[str] = field(default_factory=list)  # "deploy: Deploy to GitHub Pages"
    note: str = ""  # why the state is unknown


class DeployCheck:
    def __init__(
        self,
        gh: Runner,
        say: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll: float = 5.0,
        find_timeout: float = 90.0,
        run_timeout: float = 900.0,
    ):
        self.gh = gh
        self.say = say
        self.sleep = sleep
        self.clock = clock
        self.poll = poll
        self.find_timeout = find_timeout
        self.run_timeout = run_timeout

    # ------------------------------------------------------------ gh calls

    def _json(self, args: list[str]) -> object:
        done = self.gh(args)
        if done.returncode != 0:
            message = (done.stderr or done.stdout).strip().splitlines()
            raise RuntimeError(message[-1] if message else f"gh {args[0]} failed")
        return json.loads(done.stdout or "null")

    def find_run(self, sha: str) -> dict | None:
        """The workflow run for this commit, waiting up to find_timeout for GitHub to start it."""
        deadline = self.clock() + self.find_timeout
        while True:
            runs = self._json(
                [
                    "run", "list", "--workflow", WORKFLOW, "--limit", "20",
                    "--json", "databaseId,headSha,status,conclusion,url,event",
                ]
            )  # fmt: skip
            for run in runs or []:
                if run.get("headSha") == sha:
                    return run
            if self.clock() >= deadline:
                return None
            self.sleep(self.poll)

    def view(self, run_id: int) -> dict:
        return self._json(
            ["run", "view", str(run_id), "--json", "status,conclusion,jobs,url,attempt"]
        )

    # ------------------------------------------------------------ waiting

    def wait(self, run_id: int, after_attempt: int = 0) -> Outcome:
        """Follow the run until it finishes, printing each job as it completes.
        after_attempt: after a re-run, ignore the finished attempt until the new one starts."""
        deadline = self.clock() + self.run_timeout
        reported: set[str] = set()
        while True:
            run = self.view(run_id)
            current = int(run.get("attempt") or 1) > after_attempt
            if current:
                for job in run.get("jobs") or []:
                    name, end = job.get("name", "?"), job.get("conclusion")
                    if job.get("status") == "completed" and name not in reported:
                        reported.add(name)
                        self.say(f"  {name}: {'ok' if end == 'success' else end}")
                if run.get("status") == "completed":
                    return self._outcome(run_id, run)
            if self.clock() >= deadline:
                return Outcome("waiting", run_id, run.get("url"))
            self.sleep(self.poll)

    @staticmethod
    def _outcome(run_id: int, run: dict) -> Outcome:
        conclusion = run.get("conclusion")
        if conclusion == "success":
            return Outcome("live", run_id, run.get("url"))
        failed = [
            f"{job.get('name')}: {step.get('name')}"
            for job in run.get("jobs") or []
            for step in job.get("steps") or []
            if step.get("conclusion") == "failure"
        ]
        state = "cancelled" if conclusion == "cancelled" else "failed"
        return Outcome(state, run_id, run.get("url"), failed)

    def check(self, sha: str) -> Outcome:
        """How the run for this commit ended, waiting for it if it's still going."""
        try:
            run = self.find_run(sha)
            if run is None:
                return Outcome("unknown", note="GitHub hasn't started a deploy for this commit")
            run_id = int(run["databaseId"])
            if run.get("status") != "completed":
                self.say(
                    "Waiting for GitHub to test and deploy (Ctrl+C stops waiting, not GitHub)…"
                )
            return self.wait(run_id)
        except (RuntimeError, ValueError, KeyError) as exc:
            return Outcome("unknown", note=f"couldn't ask GitHub: {exc}")

    def rerun(self, outcome: Outcome) -> Outcome:
        """Re-run the failed jobs of a run (the deploy, usually) and wait again."""
        try:
            attempt = int(self.view(outcome.run_id).get("attempt") or 1)
            done = self.gh(["run", "rerun", str(outcome.run_id), "--failed"])
            if done.returncode != 0:
                raise RuntimeError((done.stderr or done.stdout).strip() or "gh run rerun failed")
            self.say("Trying the deploy again…")
            return self.wait(outcome.run_id, after_attempt=attempt)
        except (RuntimeError, ValueError, KeyError) as exc:
            return Outcome("unknown", outcome.run_id, outcome.url, note=f"couldn't re-run: {exc}")

    def site_url(self) -> str | None:
        try:
            url = self._json(["api", "repos/{owner}/{repo}/pages", "--jq", "{url: .html_url}"])
            return url.get("url") if isinstance(url, dict) else None
        except (RuntimeError, ValueError):
            return None


def report(outcome: Outcome, say: Callable[[str], None], site: str | None = None) -> None:
    if outcome.state == "live":
        say(f"The website is up to date{f': {site}' if site else '.'}")
        say("  (Your phone may show the old page for a few minutes; reload.)")
    elif outcome.state in ("failed", "cancelled"):
        what = "failed" if outcome.state == "failed" else "was cancelled"
        say(f"The deploy {what}, so the website still shows the previous version.")
        for step in outcome.failed_steps:
            say(f"  failed: {step}")
        say(f"  Details: gh run view {outcome.run_id} --log-failed")
        say(f"  Try again: bookshelf publish --check  (or gh run rerun {outcome.run_id} --failed)")
    elif outcome.state == "waiting":
        say("GitHub is still working on it. Check later with: bookshelf publish --check")
    else:
        say(f"Couldn't check the deploy ({outcome.note}).")
        say("  Look at the Actions tab on GitHub, or run: gh run list --workflow pages.yml")
