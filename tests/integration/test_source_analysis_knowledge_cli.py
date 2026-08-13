from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_QUOTE = "Berlin ist die Hauptstadt von Deutschland."


def _run_cli(
    root: Path,
    *args: str,
    lm_studio_base_url: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ATHENA_LOCAL_ROOT"] = str(root.resolve())
    if lm_studio_base_url is not None:
        env["ATHENA_LMSTUDIO_BASE_URL"] = lm_studio_base_url
    return subprocess.run(
        [sys.executable, "-m", "athena", *args],
        capture_output=True,
        text=True,
        input=input_text,
        env=env,
        check=False,
    )


class _SourceKnowledgeHandler(BaseHTTPRequestHandler):
    schema_names: list[str] = []
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
                        "max_context_length": 12000,
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
        schema_name = str(payload["response_format"]["json_schema"]["name"])
        type(self).schema_names.append(schema_name)
        type(self).max_tokens_seen.append(payload.get("max_tokens"))

        if schema_name == "athena_source_analysis_knowledge_extraction_v1":
            content = {
                "knowledge_units": [
                    {
                        "source_sequence_no": 1,
                        "source_quote": _QUOTE,
                        "knowledge_kind": "fact",
                        "title": "Hauptstadt Deutschlands",
                        "body": _QUOTE,
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    }
                ],
                "claims": [
                    {
                        "source_sequence_no": 1,
                        "source_quote": _QUOTE,
                        "claim_kind": "factual_assertion",
                        "statement": _QUOTE,
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    }
                ],
                "relations": [],
                "merge_candidates": [],
            }
        elif "map" in schema_name:
            content = {
                "relevant": True,
                "summary": "Berlin is named as Germany's capital.",
                "findings": [_QUOTE],
                "contradictions": [],
                "uncertainty": "",
            }
        else:
            content = {
                "summary": "Berlin is named as Germany's capital.",
                "findings": [_QUOTE],
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


def test_completed_source_analysis_can_be_promoted_from_frozen_cli_snapshot_without_second_model_call(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "source.txt"
    source_file.write_text(
        _QUOTE + " Die Quelle nennt Berlin ausdrücklich als Hauptstadt Deutschlands.",
        encoding="utf-8",
        newline="",
    )

    imported = _run_cli(local_root, "source", "import", str(source_file))
    assert imported.returncode == 0, imported.stderr
    source_match = re.search(r"(?m)^Source captured:\s*(" + _UUID_RE.pattern + r")$", imported.stdout)
    assert source_match is not None
    source_id = source_match.group(1)

    queued_source = _run_cli(local_root, "job", "source-process", source_id)
    assert queued_source.returncode == 0, queued_source.stderr
    job_match = re.search(r"(?m)^Job:\s*(" + _UUID_RE.pattern + r")$", queued_source.stdout)
    assert job_match is not None
    processed = _run_cli(
        local_root,
        "job",
        "run-source",
        job_match.group(1),
        "--worker",
        "source-knowledge-cli",
    )
    assert processed.returncode == 0, processed.stderr
    assert "Chunks: 1" in processed.stdout
    assert "Done: True" in processed.stdout

    _SourceKnowledgeHandler.schema_names = []
    _SourceKnowledgeHandler.max_tokens_seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SourceKnowledgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        queued_analysis = _run_cli(
            local_root,
            "job",
            "source-analyze",
            source_id,
            "Was sagt die Quelle über die Hauptstadt Deutschlands?",
            "--model",
            "fake-primary",
            "--context-limit",
            "6000",
            "--output-reserve",
            "1000",
            "--safety-margin",
            "300",
            lm_studio_base_url=base_url,
        )
        assert queued_analysis.returncode == 0, queued_analysis.stderr
        analysis_job = re.search(
            r"(?m)^Job:\s*(" + _UUID_RE.pattern + r")$",
            queued_analysis.stdout,
        )
        assert analysis_job is not None

        completed = _run_cli(
            local_root,
            "job",
            "run-analysis",
            analysis_job.group(1),
            "--worker",
            "source-knowledge-analysis",
            lm_studio_base_url=base_url,
        )
        assert completed.returncode == 0, completed.stderr
        assert "State: completed" in completed.stdout
        analysis_match = re.search(
            r"(?m)^Analysis:\s*(" + _UUID_RE.pattern + r")$",
            completed.stdout,
        )
        assert analysis_match is not None

        extracted = _run_cli(
            local_root,
            "extract",
            "source-analysis",
            analysis_match.group(1),
            "--model",
            "fake-primary",
            "--context-limit",
            "8000",
            "--output-reserve",
            "2048",
            "--safety-margin",
            "500",
            lm_studio_base_url=base_url,
        )
        assert extracted.returncode == 0, extracted.stderr
        assert "Evidence anchors: 1" in extracted.stdout
        assert "Knowledge proposals: 1" in extracted.stdout
        assert "Claim proposals: 1" in extracted.stdout
        assert "Canonical writes: 0 (proposal-only)" in extracted.stdout
        run_match = re.search(
            r"(?m)^Frozen source extraction run:\s*(" + _UUID_RE.pattern + r")$",
            extracted.stdout,
        )
        assert run_match is not None
        extraction_run_id = run_match.group(1)
        assert "athena_source_analysis_knowledge_extraction_v1" in _SourceKnowledgeHandler.schema_names
        extraction_index = _SourceKnowledgeHandler.schema_names.index(
            "athena_source_analysis_knowledge_extraction_v1"
        )
        assert _SourceKnowledgeHandler.max_tokens_seen[extraction_index] == 2048
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Server is gone: this command proves acceptance reloads the frozen snapshot
    # and does not make another provider/model call.
    accepted = _run_cli(
        local_root,
        "extract",
        "accept-source-run",
        extraction_run_id,
        input_text="y\n",
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "Loaded frozen source extraction proposal snapshot; Primary Model was not called." in accepted.stdout
    assert "Knowledge resolved: 1 (created=1 reused=0)" in accepted.stdout
    assert "Claims resolved: 1 (created=1 reused=0)" in accepted.stdout

    database = sqlite3.connect(local_root / "state" / "athena.db")
    try:
        assert database.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
        assert database.execute(
            "SELECT COUNT(*) FROM source_analysis_knowledge_origins"
        ).fetchone()[0] == 2
        assert database.execute(
            "SELECT COUNT(*) FROM source_extraction_result_snapshots"
        ).fetchone()[0] == 1
    finally:
        database.close()
