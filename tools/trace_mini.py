#!/usr/bin/env python3
"""Trace mini-swe-agent execution.

This wrapper runs ``minisweagent.run.mini`` under Python's tracing hooks and
writes JSONL events to a trace file. It is meant for local investigation, not
normal agent usage.

High-level API call payloads are logged in full by default after secret
redaction. Project function locals/returns are still shortened so routine
traces stay readable.

Examples:
    python tools/trace_mini.py -- -t "write a sorting script" -y --exit-immediately
    python tools/trace_mini.py --include-lines -- -t "write a sorting script" -y
    python tools/trace_mini.py --output-dir traces -- -t "write a sorting script"
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import runpy
import sys
import time
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Any

REDACTED = "<redacted>"
DEFAULT_TRACE_REPR_LEN = 240


class JsonlTraceWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", encoding="utf-8")
        self._start = time.time()

    def write(self, event: dict[str, Any]) -> None:
        event.setdefault("t", round(time.time() - self._start, 6))
        self._file.write(json.dumps(event, default=str, sort_keys=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _safe_repr(value: Any, max_len: int | None = DEFAULT_TRACE_REPR_LEN) -> str:
    try:
        text = repr(value)
    except Exception as e:
        text = f"<unrepresentable {type(value).__name__}: {e}>"
    if max_len is not None and len(text) > max_len:
        return text[:max_len] + "...<truncated>"
    return text


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(secret in key_text for secret in ("api_key", "authorization", "token", "secret", "key")):
                result[key] = REDACTED
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def install_api_wrappers(writer: JsonlTraceWriter, *, api_repr_max_len: int | None) -> None:
    """Log high-level outbound model/API calls with secrets redacted."""

    def wrap_function(module: Any, name: str, label: str) -> None:
        original = getattr(module, name, None)
        if original is None or getattr(original, "_mswea_trace_wrapped", False):
            return

        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            writer.write(
                {
                    "event": "api_call",
                    "api": label,
                    "args": _safe_repr(_redact(args), max_len=api_repr_max_len),
                    "kwargs": _safe_repr(_redact(kwargs), max_len=api_repr_max_len),
                }
            )
            try:
                result = original(*args, **kwargs)
            except Exception as e:
                writer.write(
                    {
                        "event": "api_exception",
                        "api": label,
                        "exception": _safe_repr(e, max_len=api_repr_max_len),
                    }
                )
                raise
            writer.write(
                {
                    "event": "api_return",
                    "api": label,
                    "result_type": type(result).__name__,
                    "result": _safe_repr(_redact(result), max_len=api_repr_max_len),
                }
            )
            return result

        wrapper._mswea_trace_wrapped = True
        setattr(module, name, wrapper)

    try:
        import litellm

        wrap_function(litellm, "completion", "litellm.completion")
        wrap_function(litellm, "responses", "litellm.responses")
    except Exception as e:
        writer.write({"event": "api_wrapper_skipped", "api": "litellm", "exception": _safe_repr(e)})

    try:
        import requests

        original = requests.sessions.Session.request
        if not getattr(original, "_mswea_trace_wrapped", False):

            @functools.wraps(original)
            def request_wrapper(self, method, url, **kwargs):
                writer.write(
                    {
                        "event": "api_call",
                        "api": "requests.Session.request",
                        "method": method,
                        "url": url,
                        "kwargs": _safe_repr(_redact(kwargs), max_len=api_repr_max_len),
                    }
                )
                try:
                    response = original(self, method, url, **kwargs)
                except Exception as e:
                    writer.write(
                        {
                            "event": "api_exception",
                            "api": "requests.Session.request",
                            "method": method,
                            "url": url,
                            "exception": _safe_repr(e, max_len=api_repr_max_len),
                        }
                    )
                    raise
                writer.write(
                    {
                        "event": "api_return",
                        "api": "requests.Session.request",
                        "method": method,
                        "url": url,
                        "status_code": response.status_code,
                    }
                )
                return response

            request_wrapper._mswea_trace_wrapped = True
            requests.sessions.Session.request = request_wrapper
    except Exception as e:
        writer.write({"event": "api_wrapper_skipped", "api": "requests", "exception": _safe_repr(e)})


def make_tracer(*, writer: JsonlTraceWriter, root: Path, include_lines: bool):
    root = root.resolve()

    def should_trace(filename: str) -> bool:
        try:
            Path(filename).resolve().relative_to(root)
        except ValueError:
            return False
        return True

    def trace(frame: FrameType, event: str, arg: Any):
        filename = frame.f_code.co_filename
        if not should_trace(filename):
            return trace
        if event == "line" and not include_lines:
            return trace
        payload = {
            "event": event,
            "file": str(Path(filename).resolve()),
            "line": frame.f_lineno,
            "function": frame.f_code.co_name,
        }
        if event == "call":
            payload["locals"] = {
                key: _safe_repr(_redact(value))
                for key, value in frame.f_locals.items()
                if key not in {"self", "cls"} and not key.startswith("__")
            }
        elif event == "return":
            payload["return"] = _safe_repr(_redact(arg))
        elif event == "exception":
            exc_type, exc, _tb = arg
            payload["exception_type"] = getattr(exc_type, "__name__", str(exc_type))
            payload["exception"] = _safe_repr(exc)
        writer.write(payload)
        return trace

    return trace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Exact trace file path. If omitted, a timestamped JSONL file is created in --output-dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".trace"),
        help="Directory for auto-generated timestamped trace files.",
    )
    parser.add_argument("--root", type=Path, default=Path("src/minisweagent"))
    parser.add_argument("--include-lines", action="store_true", help="Record every executed line in project files.")
    parser.add_argument("--module", default="minisweagent.run.mini", help="Module to run under tracing.")
    parser.add_argument(
        "--api-repr-len",
        type=int,
        default=0,
        help="Maximum repr length for API args/results. Use 0 for full records, which is the default.",
    )
    parser.add_argument("program_args", nargs=argparse.REMAINDER, help="Arguments passed to the traced module.")
    args = parser.parse_args()
    if args.program_args[:1] == ["--"]:
        args.program_args = args.program_args[1:]
    if args.output is None:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        args.output = args.output_dir / f"mini-trace-{timestamp}-p{os.getpid()}.jsonl"
    elif args.output.exists() and args.output.is_dir():
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        args.output = args.output / f"mini-trace-{timestamp}-p{os.getpid()}.jsonl"
    args.api_repr_max_len = None if args.api_repr_len == 0 else args.api_repr_len
    return args


def main() -> None:
    args = parse_args()
    writer = JsonlTraceWriter(args.output)
    writer.write(
        {
            "event": "trace_start",
            "module": args.module,
            "root": str(args.root.resolve()),
            "output": str(args.output.resolve()),
            "include_lines": args.include_lines,
            "api_repr_max_len": args.api_repr_max_len,
            "argv": args.program_args,
        }
    )
    install_api_wrappers(writer, api_repr_max_len=args.api_repr_max_len)
    old_argv = sys.argv[:]
    sys.argv = [args.module, *args.program_args]
    sys.settrace(make_tracer(writer=writer, root=args.root, include_lines=args.include_lines))
    try:
        runpy.run_module(args.module, run_name="__main__")
    finally:
        sys.settrace(None)
        sys.argv = old_argv
        writer.write({"event": "trace_end"})
        writer.close()
        print(f"Wrote trace to {args.output}")


if __name__ == "__main__":
    main()
