from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _run_cli(
    root: Path,
    *args: str,
    lm_studio_base_url: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(root.resolve())
    if lm_studio_base_url is not None:
        env["ATHENA_LMSTUDIO_BASE_URL"] = lm_studio_base_url
    return subprocess.run(
        [sys.executable, "-m", "athena", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class _FakeLMStudioHandler(BaseHTTPRequestHandler):
    context_failures_remaining = 1
    structured_calls = 0
    max_tokens_seen: list[int | None] = []

    def log_message(self, format: str, *args) -> None:
        del format, args

    def do_GET(self) -> None:
        if self.path != "/api/v1/models":
            self.send_error(404)
            return
        self._send_json(
            200,
            {
                "models": [
                    {
                        "key": "fake-primary",
                        "display_name": "Fake Primary",
                        "type": "llm",
                        "max_context_length": 900,
                        "quantization": {"name": "Q4"},
                        "loaded_instances": [{}],
                        "capabilities": {
                            "vision": False,
                            "trained_for_tool_use": False,
                        },
                    }
                ]
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).structured_calls += 1
        type(self).max_tokens_seen.append(payload.get("max_tokens"))
        if type(self).context_failures_remaining > 0:
            type(self).context_failures_remaining -= 1
            self._send_json(
                400,
                {"error": {"message": "maximum context length exceeded: too many tokens"}},
            )
            return

        schema_name = payload["response_format"]["json_schema"]["name"]
        if "map" in schema_name:
            content = {
                "relevant": True,
                "summary": "map summary",
                "findings": ["map finding"],
                "contradictions": [],
                "uncertainty": "",
            }
        else:
            content = {
                "summary": "synthesis summary",
                "findings": ["synthesis finding"],
                "contradictions": [],
                "uncertainty": "",
            }
        self._send_json(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(content),
                        }
                    }
                ]
            },
        )

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_large_source_analysis_cli_splits_real_http_context_error_and_completes(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "analysis-source.md"
    source_file.write_text(
        ("alpha durable evidence " * 150)
        + "\n\n"
        + ("beta durable evidence " * 150)
        + "\n\n"
        + ("gamma durable evidence " * 150),
        encoding="utf-8",
        newline="",
    )

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    source_match = _UUID_RE.search(imported.stdout)
    assert source_match is not None
    source_id = source_match.group(0)

    queued_source = _run_cli(local_root, "job", "source-process", source_id)
    assert queued_source.returncode == 0, queued_source.stderr
    source_job_match = _UUID_RE.search(queued_source.stdout)
    assert source_job_match is not None
    processed = _run_cli(
        local_root,
        "job",
        "run-source",
        source_job_match.group(0),
        "--worker",
        "analysis-cli-source",
    )
    assert processed.returncode == 0, processed.stderr
    assert "Done: True" in processed.stdout

    _FakeLMStudioHandler.context_failures_remaining = 1
    _FakeLMStudioHandler.structured_calls = 0
    _FakeLMStudioHandler.max_tokens_seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLMStudioHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        queued = _run_cli(
            local_root,
            "job",
            "source-analyze",
            source_id,
            "Summarize all durable evidence.",
            "--model",
            "fake-primary",
            "--context-limit",
            "900",
            "--output-reserve",
            "100",
            "--safety-margin",
            "50",
            lm_studio_base_url=base_url,
        )
        assert queued.returncode == 0, queued.stderr
        job_match = _UUID_RE.search(queued.stdout)
        assert job_match is not None
        analysis_job_id = job_match.group(0)
        assert '"pipeline_version":"source-analysis-v1"' in queued.stdout

        completed = _run_cli(
            local_root,
            "job",
            "run-analysis",
            analysis_job_id,
            "--worker",
            "analysis-cli-worker",
            lm_studio_base_url=base_url,
        )
        assert completed.returncode == 0, completed.stderr
        assert "State: completed" in completed.stdout
        assert "Coverage: 1.000000" in completed.stdout
        assert "Done: True" in completed.stdout
        ids = _UUID_RE.findall(completed.stdout)
        assert len(ids) >= 3
        analysis_id = ids[2]

        shown = _run_cli(
            local_root,
            "job",
            "analysis-show",
            analysis_id,
            lm_studio_base_url=base_url,
        )
        assert shown.returncode == 0, shown.stderr
        assert "State: completed" in shown.stdout
        assert "Coverage: 1.000000" in shown.stdout
        assert "Final artifact: " in shown.stdout

        artifacts = _run_cli(
            local_root,
            "job",
            "analysis-artifacts",
            analysis_id,
            lm_studio_base_url=base_url,
        )
        assert artifacts.returncode == 0, artifacts.stderr
        assert "kind=map" in artifacts.stdout
        assert "kind=final" in artifacts.stdout
        assert "anchors=" in artifacts.stdout
        assert _FakeLMStudioHandler.context_failures_remaining == 0
        assert _FakeLMStudioHandler.structured_calls > 1
        assert _FakeLMStudioHandler.max_tokens_seen
        assert set(_FakeLMStudioHandler.max_tokens_seen) == {100}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
