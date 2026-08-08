"""Eval questions with checkable facts, and the grader that checks answers against them."""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from metric_helpdesk.models import QueryRequest
from metric_helpdesk.tools import HelpDesk


class ValueSpec(BaseModel):
    """A number the answer must contain, computed from the warehouse at grading time.

    With ``top_of``, the expected text is instead the dimension value with the largest metric.
    """

    metric: str
    start: date
    end: date
    top_of: str | None = None


class EvalQuestion(BaseModel):
    id: str
    question: str
    must_call: list[str] = Field(default_factory=list)
    must_mention: list[str] = Field(default_factory=list)
    values: list[ValueSpec] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def load_questions(path: Path) -> list[EvalQuestion]:
    return [EvalQuestion.model_validate(item) for item in yaml.safe_load(path.read_text())]


def number_variants(value: float, is_rate: bool) -> list[str]:
    """Ways an answer might print a number: 92,378 / 92378 / 92,377.90 / 92.4k; 15.7% / 16%."""
    if is_rate:
        percent = value * 100
        return [f"{percent:.1f}%", f"{percent:.2f}%", f"{percent:.0f}%"]
    variants = [f"{value:,.0f}", f"{value:.0f}", f"{value:,.2f}", f"{value:.2f}"]
    if abs(value) >= 1000:
        variants += [f"{value / 1000:.1f}k", f"{value / 1000:.1f}K", f"{value / 1000:.0f}k"]
    return variants


def expected_text(helpdesk: HelpDesk, spec: ValueSpec) -> list[str]:
    """Acceptable spellings of the expected value."""
    request = QueryRequest(
        metrics=[spec.metric],
        grain=None,
        start_date=spec.start,
        end_date=spec.end,
        group_by=[spec.top_of] if spec.top_of else [],
    )
    rows = helpdesk.query_metrics(request).rows
    if spec.top_of:
        top = max(rows, key=lambda row: row[spec.metric] or 0)
        return [str(top[spec.top_of])]
    is_rate = helpdesk.catalog.metric(spec.metric).type == "ratio"
    return number_variants(float(rows[0][spec.metric]), is_rate)


def grade(
    helpdesk: HelpDesk, question: EvalQuestion, answer: str, tools_called: list[str]
) -> list[Check]:
    """Check one answer and its tool calls against the question's expectations."""
    checks = [
        Check(f"called {tool}", tool in tools_called, ", ".join(tools_called) or "no calls")
        for tool in question.must_call
    ]
    checks += [
        Check(f"mentions /{pattern}/", bool(re.search(pattern, answer, re.IGNORECASE)), "")
        for pattern in question.must_mention
    ]
    for spec in question.values:
        variants = expected_text(helpdesk, spec)
        # Numbers must match exactly; names (top_of) are matched regardless of case.
        haystack, needles = (
            (answer.lower(), [v.lower() for v in variants])
            if spec.top_of
            else (
                answer,
                variants,
            )
        )
        found = any(needle in haystack for needle in needles)
        checks.append(Check(f"states {spec.metric}", found, f"expected one of {variants[:3]}"))
    checks += [
        Check(f"avoids /{pattern}/", not re.search(pattern, answer, re.IGNORECASE), "")
        for pattern in question.must_not
    ]
    return checks


@dataclass
class RunOutput:
    answer: str
    tools_called: list[str]


class EvalRunError(RuntimeError):
    """Raised when a runner cannot produce an answer."""


def run_claude_code(question: str, project_root: Path, model: str | None = None) -> RunOutput:
    """Ask headless Claude Code, connected only to this project's MCP server.

    Uses the caller's Claude Code login, so it runs on their subscription. Tool calls are read
    from the server's call log because Claude Code's JSON output does not include them.
    """
    import json
    import os
    import subprocess
    import tempfile

    from metric_helpdesk.server import CALL_LOG_ENV

    with tempfile.TemporaryDirectory() as tmp:
        call_log = Path(tmp) / "calls.jsonl"
        command = [
            "claude", "-p", question, "--output-format", "json",
            "--mcp-config", ".mcp.json", "--strict-mcp-config",
            "--allowedTools", "mcp__metric-helpdesk",
        ]  # fmt: skip
        if model:
            command += ["--model", model]
        completed = subprocess.run(
            command,
            cwd=project_root,
            env={**os.environ, CALL_LOG_ENV: str(call_log)},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            raise EvalRunError(f"claude exited {completed.returncode}: {completed.stderr[-500:]}")
        result = json.loads(completed.stdout)
        if result.get("is_error"):
            raise EvalRunError(f"claude reported an error: {result.get('result')}")
        calls = []
        if call_log.exists():
            calls = [json.loads(line)["tool"] for line in call_log.read_text().splitlines()]
        return RunOutput(answer=str(result.get("result", "")), tools_called=calls)
