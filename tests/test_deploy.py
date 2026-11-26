"""Following GitHub's deploy after `bookshelf publish`, with a fake gh."""

import json
import subprocess

import pytest

from bookshelf import cli_books
from bookshelf.deploy import DeployCheck, Outcome, report
from bookshelf.publish import pushed_commit

SHA = "a" * 40


def job(name, status="completed", conclusion="success", failed_step=None):
    steps = [{"name": "Set up job", "conclusion": "success"}]
    if failed_step:
        steps.append({"name": failed_step, "conclusion": "failure"})
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "steps": steps,
    }


def view(status, conclusion=None, jobs=(), attempt=1):
    return {
        "status": status,
        "conclusion": conclusion,
        "jobs": list(jobs),
        "url": "https://github.com/run/7",
        "attempt": attempt,
    }


class FakeGH:
    """Answers `run list` from a list of run lists and `run view` from a list of views,
    one per call (the last answer repeats). Records every command."""

    def __init__(self, lists=(), views=(), rerun_ok=True, pages=None, fail_list=False):
        self.lists = list(lists) or [[{"databaseId": 7, "headSha": SHA, "status": "in_progress"}]]
        self.views = list(views)
        self.rerun_ok = rerun_ok
        self.pages = pages
        self.fail_list = fail_list
        self.calls = []

    def _next(self, queue):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def __call__(self, args):
        self.calls.append(args)
        out, code, err = "", 0, ""
        if args[:2] == ["run", "list"]:
            if self.fail_list:
                code, err = (
                    1,
                    "error connecting to api.github.com\nnot logged in: run gh auth login",
                )
            else:
                out = json.dumps(self._next(self.lists))
        elif args[:2] == ["run", "view"]:
            out = json.dumps(self._next(self.views))
        elif args[:2] == ["run", "rerun"]:
            code = 0 if self.rerun_ok else 1
            err = "" if self.rerun_ok else "run 7 cannot be rerun"
        elif args[0] == "api":
            out, code = (json.dumps({"url": self.pages}), 0) if self.pages else ("", 1)
        return subprocess.CompletedProcess(args, code, out, err)


def checker(gh, said):
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    return DeployCheck(
        gh,
        said.append,
        sleep=sleep,
        clock=lambda: clock[0],
        poll=5,
        find_timeout=30,
        run_timeout=60,
    )


def test_waits_and_reports_each_job_then_live():
    gh = FakeGH(
        views=[
            view("in_progress", jobs=[job("test", "in_progress")]),
            view("in_progress", jobs=[job("test"), job("build", "in_progress")]),
            view("completed", "success", jobs=[job("test"), job("build"), job("deploy")]),
        ]
    )
    said = []
    outcome = checker(gh, said).check(SHA)
    assert (outcome.state, outcome.run_id) == ("live", 7)
    assert said == [
        "Waiting for GitHub to test and deploy (Ctrl+C stops waiting, not GitHub)…",
        "  test: ok",
        "  build: ok",
        "  deploy: ok",
    ]


def test_waits_for_the_run_to_appear():
    gh = FakeGH(
        lists=[
            [],
            [{"databaseId": 9, "headSha": "b" * 40}],
            [{"databaseId": 7, "headSha": SHA, "status": "completed"}],
        ],
        views=[view("completed", "success")],
    )
    outcome = checker(gh, []).check(SHA)
    assert outcome.state == "live"
    assert sum(c[:2] == ["run", "list"] for c in gh.calls) == 3


def test_no_run_for_the_commit():
    gh = FakeGH(lists=[[{"databaseId": 9, "headSha": "b" * 40}]])
    outcome = checker(gh, []).check(SHA)
    assert (outcome.state, outcome.note) == (
        "unknown",
        "GitHub hasn't started a deploy for this commit",
    )


def test_failed_deploy_names_the_step():
    gh = FakeGH(
        views=[
            view(
                "completed",
                "failure",
                jobs=[
                    job("test"),
                    job("build"),
                    job("deploy", conclusion="failure", failed_step="Run actions/deploy-pages@v4"),
                ],
            )
        ]
    )
    outcome = checker(gh, []).check(SHA)
    assert outcome.state == "failed"
    assert outcome.failed_steps == ["deploy: Run actions/deploy-pages@v4"]


def test_gives_up_waiting_after_the_timeout():
    gh = FakeGH(views=[view("queued")])
    assert checker(gh, []).check(SHA).state == "waiting"


def test_gh_not_logged_in_is_unknown_with_the_reason():
    outcome = checker(FakeGH(fail_list=True), []).check(SHA)
    assert outcome.state == "unknown"
    assert outcome.note == "couldn't ask GitHub: not logged in: run gh auth login"


def test_rerun_waits_for_the_new_attempt():
    gh = FakeGH(
        views=[
            view("completed", "failure", attempt=1),  # read before re-running
            view("completed", "failure", attempt=1),  # GitHub hasn't started attempt 2 yet
            view("in_progress", attempt=2, jobs=[job("test"), job("build")]),
            view(
                "completed", "success", attempt=2, jobs=[job("test"), job("build"), job("deploy")]
            ),
        ]
    )
    said = []
    outcome = checker(gh, said).rerun(Outcome("failed", 7))
    assert outcome.state == "live"
    assert ["run", "rerun", "7", "--failed"] in gh.calls
    assert said == ["Trying the deploy again…", "  test: ok", "  build: ok", "  deploy: ok"]


def test_rerun_refused():
    gh = FakeGH(views=[view("completed", "failure")], rerun_ok=False)
    outcome = checker(gh, []).rerun(Outcome("failed", 7))
    assert (outcome.state, outcome.note) == ("unknown", "couldn't re-run: run 7 cannot be rerun")


def test_report_texts():
    said = []
    report(Outcome("live"), said.append, site="https://kokyudosa.github.io/bookshelf/")
    report(Outcome("failed", 7, failed_steps=["deploy: Run actions/deploy-pages@v4"]), said.append)
    report(Outcome("waiting"), said.append)
    report(Outcome("unknown", note="gh isn't logged in"), said.append)
    text = "\n".join(said)
    assert "The website is up to date: https://kokyudosa.github.io/bookshelf/" in text
    assert "The deploy failed, so the website still shows the previous version." in text
    assert "failed: deploy: Run actions/deploy-pages@v4" in text
    assert "gh run view 7 --log-failed" in text
    assert "bookshelf publish --check" in text
    assert "Couldn't check the deploy (gh isn't logged in)." in text


# ---------------------------------------------------------------- the command


@pytest.fixture
def wired(monkeypatch):
    """check_deploy with a fake gh and a pushed commit, no real waiting."""
    holder = {}

    def use(gh):
        holder["gh"] = gh
        monkeypatch.setattr(cli_books, "gh_runner", lambda repo: gh)
        monkeypatch.setattr(cli_books, "pushed_commit", lambda repo: (SHA, False))
        real = DeployCheck.__init__

        def fast(self, gh, say=print, **kw):
            real(self, gh, say, sleep=lambda s: None, poll=0, find_timeout=0, run_timeout=0)

        monkeypatch.setattr(DeployCheck, "__init__", fast)
        return gh

    return use


def test_check_deploy_live(wired, capsys):
    wired(
        FakeGH(views=[view("completed", "success")], pages="https://kokyudosa.github.io/bookshelf/")
    )
    assert cli_books.check_deploy(retry=lambda q: True) == 0
    assert (
        "The website is up to date: https://kokyudosa.github.io/bookshelf/"
        in capsys.readouterr().out
    )


def test_check_deploy_failed_then_retry_succeeds(wired, capsys):
    gh = wired(
        FakeGH(
            views=[
                view(
                    "completed",
                    "failure",
                    jobs=[
                        job(
                            "deploy",
                            conclusion="failure",
                            failed_step="Run actions/deploy-pages@v4",
                        )
                    ],
                ),
                view("completed", "failure"),  # attempt read before the re-run
                view("completed", "success", attempt=2),
            ]
        )
    )
    asked = []
    assert cli_books.check_deploy(retry=lambda q: asked.append(q) or True) == 0
    out = capsys.readouterr().out
    assert asked == ["Try the deploy again?"]
    assert "The deploy failed" in out and "Trying the deploy again…" in out and "up to date" in out
    assert ["run", "rerun", "7", "--failed"] in gh.calls


def test_check_deploy_failed_and_declined(wired, capsys):
    wired(FakeGH(views=[view("completed", "failure")]))
    assert cli_books.check_deploy(retry=lambda q: False) == 1
    assert "still shows the previous version" in capsys.readouterr().out


def test_check_deploy_without_gh(monkeypatch, capsys):
    monkeypatch.setattr(cli_books, "gh_runner", lambda repo: None)
    assert cli_books.check_deploy(retry=lambda q: True) == 0
    assert "the GitHub CLI (gh) isn't installed" in capsys.readouterr().out


def test_check_deploy_ctrl_c(wired, monkeypatch, capsys):
    wired(FakeGH())

    def interrupted(self, sha):
        raise KeyboardInterrupt

    monkeypatch.setattr(DeployCheck, "check", interrupted)
    assert cli_books.check_deploy(retry=lambda q: True) == 0
    assert "Stopped waiting; GitHub carries on" in capsys.readouterr().out


def test_publish_check_and_no_wait_options(monkeypatch, db_path, capsys):
    calls = []
    monkeypatch.setattr(cli_books, "check_deploy", lambda retry: calls.append("check") or 0)
    monkeypatch.setattr(cli_books, "publish", lambda *a, **k: calls.append("publish") or False)
    from bookshelf.cli import main

    assert main(["--db", str(db_path), "publish", "--check"]) == 0
    assert main(["--db", str(db_path), "publish", "--no-wait", "-y"]) == 0
    assert main(["--db", str(db_path), "publish", "-y"]) == 0
    assert main(["--db", str(db_path), "publish", "--no-push", "-y"]) == 0
    assert calls == ["check", "publish", "publish", "check", "publish"]


# ---------------------------------------------------------------- which commit GitHub has


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_pushed_commit(tmp_path):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    for key, value in (
        ("user.email", "t@example.com"),
        ("user.name", "T"),
        ("commit.gpgsign", "false"),
    ):
        git(work, "config", key, value)
    assert pushed_commit(work) == (None, False)  # no upstream
    git(work, "commit", "-q", "--allow-empty", "-m", "one")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "-u", "origin", "main")
    first = git(work, "rev-parse", "HEAD")
    assert pushed_commit(work) == (first, False)
    git(work, "commit", "-q", "--allow-empty", "-m", "two")
    assert pushed_commit(work) == (first, True)  # local commit not pushed yet
