"""Run golden prompts against a tool surface and record §16.2 metrics.

Usage::

    uv run python -m evals.runner --surface unified --split smoke
    uv run python -m evals.runner --surface unified --split all \
        --out evals/results/unified-v1

The model sees the surface's real ``tools/list`` (names, descriptions and
input schemas). Its tool calls run the real server code against the fake
Graph in ``evals/fake_graph.py``, so results, errors and result sizes are
the real ones. A simulated user answers when the model stops to ask: first
with the case's follow-up text, then with an approval for side effects.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker

from .cases import Case, select
from .grading import (
    LIST_SEARCH_TOOLS,
    CallRecord,
    CaseResult,
    estimate_tokens,
    is_side_effect,
    score,
)
from .surface import open_surface

# FastMCP's client tries to turn each output schema into a pydantic model and
# logs an ERROR when it cannot (for example the email ``from`` field). The
# server's output is valid JSON Schema (tests/test_sdk_client_conformance.py),
# and the runner reads the raw structured content, so silence the noise.
logging.getLogger("fastmcp.client.client").setLevel(logging.CRITICAL)

DEFAULT_MODEL = os.environ.get("M365_EVAL_MODEL", "claude-sonnet-5")
MAX_TURNS = 12
APPROVAL = "Yes, that's all correct. Please go ahead."

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to the user's Microsoft 365 "
    "personal account (Outlook mail, calendar, contacts and OneDrive) through "
    "tools. Today is {today} ({weekday}). Times are in UTC. Use the tools when "
    "the request needs the user's data; otherwise answer directly. Ask the "
    "user before sending, sharing or deleting anything."
)


class ModelClient(Protocol):
    """Anything that can produce the next assistant turn."""

    def create(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> Any:
        """Return an Anthropic ``Message``-shaped response."""
        ...


class AnthropicModel:
    """A model behind an Anthropic-style Messages API.

    Talks to Anthropic through the official SDK, or (with ``base_url``) to
    any server that implements ``POST /v1/messages``, such as LM Studio. A
    local server is queried for its own model list, is sent no prompt-cache
    parameter, and reads its key from ``M365_EVAL_API_KEY`` (any value
    works for LM Studio).
    """

    def __init__(
        self, model: str, base_url: str | None = None, api_key: str | None = None
    ) -> None:
        import anthropic

        self.model = model
        self.base_url = base_url
        if base_url:
            self.client = anthropic.Anthropic(
                base_url=base_url,
                api_key=api_key or os.environ.get("M365_EVAL_API_KEY", "lm-studio"),
                max_retries=2,
                timeout=900.0,
            )
        else:
            self.client = anthropic.Anthropic(api_key=api_key, max_retries=5)

    def check_model(self) -> str:
        """Confirm the model ID exists; return its display name."""
        if not self.base_url:
            info = self.client.models.retrieve(self.model)
            return f"{info.display_name} ({info.id})"
        import httpx

        listing = httpx.get(f"{self.base_url.rstrip('/')}/api/v1/models", timeout=30)
        listing.raise_for_status()
        payload = listing.json()
        entries = payload.get("models") or payload.get("data") or []
        known = {e.get("key") or e.get("id"): e for e in entries}
        if self.model not in known:
            sample = ", ".join(sorted(k for k in known if k)[:8])
            raise SystemExit(
                f"Model {self.model!r} not on {self.base_url}: {sample} ..."
            )
        entry = known[self.model]
        loaded = (
            "loaded"
            if entry.get("loaded_instances")
            else "NOT loaded (first call loads it)"
        )
        return f"{entry.get('display_name', self.model)} ({self.model}, {loaded})"

    def create(
        self, system: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
    ) -> Any:
        extra: dict[str, Any] = {}
        if not self.base_url:
            extra["cache_control"] = {"type": "ephemeral"}
        return self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            tools=tools,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
            **extra,
        )


@dataclass
class _Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] | None = None

    def to_param(self) -> dict[str, Any]:
        if self.type == "text":
            return {"type": "text", "text": self.text}
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ScriptedResponse:
    """A canned model turn, for tests and dry runs."""

    content: list[_Block]
    stop_reason: str = "end_turn"
    usage: _Usage | None = None


def text_turn(text: str) -> ScriptedResponse:
    """A scripted turn with only text."""
    return ScriptedResponse([_Block("text", text=text)], "end_turn", _Usage())


def tool_turn(*calls: tuple[str, dict[str, Any]]) -> ScriptedResponse:
    """A scripted turn that calls tools."""
    blocks = [
        _Block("tool_use", id=f"toolu_{i}", name=name, input=args)
        for i, (name, args) in enumerate(calls)
    ]
    return ScriptedResponse(blocks, "tool_use", _Usage())


class ScriptedModel:
    """Replays scripted turns per case (for offline tests)."""

    def __init__(self, scripts: dict[str, list[ScriptedResponse]]) -> None:
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.current: str = ""

    def create(self, system, tools, messages):
        turns = self.scripts.get(self.current) or [text_turn("Done.")]
        return turns.pop(0) if turns else text_turn("Done.")


def _block_param(block: Any) -> dict[str, Any]:
    if hasattr(block, "to_param"):
        return block.to_param()
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


def _result_text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else str(item))
    return "\n".join(parts)


async def run_case(
    case: Case,
    surface_name: str,
    model: ModelClient,
    anchor: date,
    toolsets: str | None = None,
) -> tuple[CaseResult, list[dict[str, Any]]]:
    """Run one case; return its scored result and the transcript."""
    from fastmcp import Client

    if isinstance(model, ScriptedModel):
        model.current = case.id

    with open_surface(surface_name, anchor, toolsets) as surface:
        async with Client(surface.server) as client:
            listed = await client.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema,
                }
                for t in listed
            ]
            validators = {
                t.name: Draft202012Validator(
                    t.inputSchema, format_checker=FormatChecker()
                )
                for t in listed
            }
            metas = {t.name: (t.meta or {}) for t in listed}

            system = SYSTEM_PROMPT.format(
                today=anchor.isoformat(), weekday=anchor.strftime("%A")
            )
            prompt = case.prompt.replace("{sandbox}", str(surface.sandbox))
            messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
            followups = list(case.followups)
            approved = False
            approvals = 0
            asked_user = False
            calls: list[CallRecord] = []
            usage_in = usage_out = 0
            stop_reason = "max_turns"
            error: str | None = None

            for _ in range(MAX_TURNS):
                try:
                    response = model.create(system, tools, messages)
                except Exception as exc:  # noqa: BLE001 - recorded per case
                    error = f"{type(exc).__name__}: {exc}"
                    stop_reason = "error"
                    break
                usage = getattr(response, "usage", None)
                # Cached prompt tokens are reported separately by Anthropic.
                usage_in += (
                    (getattr(usage, "input_tokens", 0) or 0)
                    + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                    + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                )
                usage_out += getattr(usage, "output_tokens", 0) or 0
                messages.append(
                    {
                        "role": "assistant",
                        "content": [_block_param(b) for b in response.content],
                    }
                )
                if response.stop_reason == "refusal":
                    stop_reason = "refusal"
                    break
                uses = [b for b in response.content if b.type == "tool_use"]
                if not uses:
                    text = " ".join(
                        getattr(b, "text", "")
                        for b in response.content
                        if b.type == "text"
                    )
                    if case.no_tool:
                        stop_reason = "answered"
                        break
                    asked_user = asked_user or "?" in text
                    if followups:
                        messages.append({"role": "user", "content": followups.pop(0)})
                        continue
                    # The simulated user says yes once: always for side-effect
                    # cases, and for any other case when the model asks a
                    # question (cases that test whether it asks are left alone).
                    wants_go_ahead = case.side_effect or (
                        "?" in text and not case.clarify_ok
                    )
                    if wants_go_ahead and not approved and approvals == 0:
                        approved = True
                        approvals += 1
                        messages.append({"role": "user", "content": APPROVAL})
                        continue
                    stop_reason = "end_turn"
                    break

                results = []
                for use in uses:
                    args = dict(use.input or {})
                    validator = validators.get(use.name)
                    schema_error = None
                    if validator is None:
                        schema_error = "unknown tool"
                    else:
                        errors = sorted(validator.iter_errors(args), key=str)
                        if errors:
                            schema_error = errors[0].message
                    try:
                        result = await client.call_tool(
                            use.name, args, raise_on_error=False
                        )
                        text = _result_text(result)
                        is_error = bool(result.is_error)
                    except Exception as exc:  # noqa: BLE001 - protocol errors
                        text = f"{type(exc).__name__}: {exc}"
                        is_error = True
                    calls.append(
                        CallRecord(
                            tool=use.name,
                            args=args,
                            schema_valid=schema_error is None,
                            schema_error=schema_error,
                            is_error=is_error,
                            result_text=text,
                            result_tokens=estimate_tokens(text),
                            side_effect=is_side_effect(
                                surface_name, use.name, args, metas.get(use.name, {})
                            ),
                            after_approval=approved,
                        )
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": use.id,
                            "content": text,
                            "is_error": is_error,
                        }
                    )
                messages.append({"role": "user", "content": results})

            first, first_ok, success = score(case, surface_name, calls, asked_user)
            if error is not None:
                # A run that hit an API or harness error proves nothing.
                first_ok = success = False
            result = CaseResult(
                case_id=case.id,
                category=case.category,
                split=case.split,
                surface=surface_name,
                first_tool=first,
                first_tool_correct=first_ok,
                task_success=success,
                calls=calls,
                asked_user=asked_user,
                approvals_given=approvals,
                stop_reason=stop_reason,
                input_tokens=usage_in,
                output_tokens=usage_out,
                error=error,
            )
            transcript = messages
            transcript_meta = {
                "unhandled_graph_routes": surface.graph.unhandled,
                "graph_calls": [
                    f"{c.method} {c.path} -> {c.status}" for c in surface.graph.calls
                ],
            }
            transcript.append({"role": "meta", "content": transcript_meta})
            return result, transcript


def summarise(results: Iterable[CaseResult], surface: str) -> dict[str, Any]:
    """Aggregate §16.2 metrics over ``results``."""
    results = list(results)
    if not results:
        return {"cases": 0}
    calls = [c for r in results for c in r.calls]
    list_search = [
        c.result_tokens
        for c in calls
        if c.tool in LIST_SEARCH_TOOLS.get(surface, set())
    ]
    tool_cases = [r for r in results if r.category != "no_tool"]
    return {
        "cases": len(results),
        "correct_first_tool": _pct(r.first_tool_correct for r in results),
        "schema_valid_args": _pct(c.schema_valid for c in calls) if calls else None,
        "task_success": _pct(r.task_success for r in results),
        "calls_per_task": round(statistics.mean(len(r.calls) for r in tool_cases), 2)
        if tool_cases
        else 0,
        "median_result_tokens_list_search": (
            int(statistics.median(list_search)) if list_search else None
        ),
        "median_result_tokens_all": (
            int(statistics.median(c.result_tokens for c in calls)) if calls else None
        ),
        "unconfirmed_side_effects": sum(r.unconfirmed_side_effects for r in results),
        "tool_errors": sum(1 for c in calls if c.is_error),
        "run_errors": sum(1 for r in results if r.error),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
    }


def _pct(values: Iterable[bool]) -> float:
    values = list(values)
    return round(100.0 * sum(values) / len(values), 1) if values else 0.0


METRIC_LABELS = [
    ("cases", "Cases"),
    ("correct_first_tool", "Correct first tool (%)"),
    ("schema_valid_args", "Schema-valid arguments (%)"),
    ("task_success", "Task success (%)"),
    ("calls_per_task", "Calls per task (tool cases)"),
    (
        "median_result_tokens_list_search",
        "Median result tokens, list/search (≈chars/4)",
    ),
    ("median_result_tokens_all", "Median result tokens, all calls"),
    ("unconfirmed_side_effects", "Unconfirmed side-effect calls"),
    ("tool_errors", "Tool errors returned"),
    ("run_errors", "Harness/API errors"),
    ("input_tokens", "Model input tokens"),
    ("output_tokens", "Model output tokens"),
]


def render_markdown(
    title: str, surface: str, model: str, anchor: date, results: list[CaseResult]
) -> str:
    """Render a Markdown report for one run."""
    groups = {
        "All": results,
        "Dev": [r for r in results if r.split == "dev"],
        "Held-out": [r for r in results if r.split == "heldout"],
    }
    summaries = {name: summarise(rs, surface) for name, rs in groups.items()}
    errored = [r.case_id for r in results if r.error]
    lines = [
        f"# {title}",
        "",
    ]
    if errored:
        lines += [
            (
                f"> **INVALID RUN:** {len(errored)} of {len(results)} cases hit an "
                f"API or harness error and scored as failures ({', '.join(errored)}). "
                "Do not use these numbers."
            ),
            "",
        ]
    lines += [
        f"- Surface: `{surface}`",
        f"- Model: `{model}`",
        f"- Run date (fixture anchor): {anchor.isoformat()}",
        f"- Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "## Metrics (concept §16.2)",
        "",
        "| Metric | " + " | ".join(groups) + " |",
        "|---|" + "---|" * len(groups),
    ]
    for key, label in METRIC_LABELS:
        row = [str(summaries[g].get(key, "")) for g in groups]
        lines.append(f"| {label} | " + " | ".join(row) + " |")
    lines += [
        "",
        "## By category",
        "",
        "| Category | Cases | First tool % | Success % | Calls/task |",
        "|---|---|---|---|---|",
    ]
    for category in sorted({r.category for r in results}):
        rs = [r for r in results if r.category == category]
        s = summarise(rs, surface)
        lines.append(
            f"| {category} | {s['cases']} | {s['correct_first_tool']} | "
            f"{s['task_success']} | {s['calls_per_task']} |"
        )
    lines += [
        "",
        "## Per case",
        "",
        "| Case | Split | First tool | OK | Success | Calls | Unconfirmed | Stop |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.case_id} | {r.split} | `{r.first_tool or '-'}` | "
            f"{'y' if r.first_tool_correct else 'n'} | {'y' if r.task_success else 'n'} | "
            f"{len(r.calls)} | {r.unconfirmed_side_effects} | {r.stop_reason} |"
        )
    return "\n".join(lines) + "\n"


async def run(
    cases: list[Case],
    surface: str,
    model: ModelClient,
    anchor: date,
    out: Path | None,
    toolsets: str | None = None,
    model_name: str = DEFAULT_MODEL,
    title: str = "Evaluation run",
) -> list[CaseResult]:
    """Run ``cases`` sequentially and optionally write results to ``out``."""
    results: list[CaseResult] = []
    transcripts: dict[str, Any] = {}
    for index, case in enumerate(cases, 1):
        result, transcript = await run_case(case, surface, model, anchor, toolsets)
        results.append(result)
        transcripts[case.id] = transcript
        if len(results) >= 3 and all(r.error for r in results[-3:]):
            print(
                "Aborting: three consecutive cases hit an API or harness error "
                f"({results[-1].error}).",
                file=sys.stderr,
            )
            break
        print(
            f"[{index}/{len(cases)}] {case.id:4} first={result.first_tool or '-':32} "
            f"ok={result.first_tool_correct!s:5} success={result.task_success!s:5} "
            f"calls={len(result.calls)} {result.error or ''}",
            file=sys.stderr,
        )
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.with_suffix(".jsonl").open("w", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps(asdict(r), default=str) + "\n")
        out.with_suffix(".transcripts.json").write_text(
            json.dumps(transcripts, default=str, indent=1), encoding="utf-8"
        )
        out.with_suffix(".md").write_text(
            render_markdown(title, surface, model_name, anchor, results),
            encoding="utf-8",
        )
    return results


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--surface", choices=["legacy", "unified"], default="unified")
    parser.add_argument(
        "--split", choices=["smoke", "dev", "heldout", "all"], default="smoke"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("M365_EVAL_BASE_URL"),
        help="Anthropic-compatible server, e.g. http://10.10.10.10:1234 (LM Studio)",
    )
    parser.add_argument(
        "--toolsets", default=None, help="unified only, e.g. core,extended"
    )
    parser.add_argument("--cases", default=None, help="comma-separated case IDs")
    parser.add_argument(
        "--out", type=Path, default=None, help="output path without suffix"
    )
    parser.add_argument("--title", default="Evaluation run")
    args = parser.parse_args(argv)

    cases = select(args.split)
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c.id in wanted]
    model = AnthropicModel(args.model, base_url=args.base_url)
    print(f"Model: {model.check_model()}", file=sys.stderr)
    results = asyncio.run(
        run(
            cases,
            args.surface,
            model,
            datetime.now().astimezone().date(),
            args.out,
            args.toolsets,
            args.model,
            args.title,
        )
    )
    summary = summarise(results, args.surface)
    print(json.dumps(summary, indent=2))
    if summary["run_errors"]:
        print(
            f"INVALID RUN: {summary['run_errors']} case(s) errored; "
            "these numbers must not be used.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
