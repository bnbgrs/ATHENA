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


class _HierarchicalExtractionHandler(BaseHTTPRequestHandler):
    schema_names: list[str] = []
    extraction_calls = 0
    merge_calls = 0
    audit_calls = 0
    native_payloads: list[dict[str, object]] = []

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
                        "max_context_length": 6000,
                        "quantization": {"name": "Q4"},
                        "loaded_instances": [{"config": {"context_length": 6000}}],
                        "capabilities": {
                            "vision": False,
                            "trained_for_tool_use": False,
                            "reasoning": {
                                "allowed_options": ["off", "on"],
                                "default": "on",
                            },
                        },
                    }
                ]
            },
        )

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))

        if self.path == "/v1/chat/completions":
            response_format = payload["response_format"]["json_schema"]
            schema_name = str(response_format["name"])
            user = str(payload["messages"][-1]["content"])
            content = self._content_for_schema(schema_name, user)
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
            return

        if self.path == "/api/v1/chat":
            type(self).native_payloads.append(payload)
            system_prompt = str(payload.get("system_prompt", ""))
            match = re.search(r"(?m)^ATHENA_SCHEMA_ID: ([^\r\n]+)$", system_prompt)
            if match is None:
                self._send_json(500, {"error": {"message": "missing ATHENA schema id"}})
                return
            schema_name = match.group(1)
            user = str(payload.get("input", ""))
            content = self._content_for_schema(schema_name, user)
            self._send_json(
                200,
                {
                    "model_instance_id": "fake-primary:runtime-1",
                    "output": [{"type": "message", "content": json.dumps(content)}],
                    "stats": {
                        "input_tokens": 100,
                        "total_output_tokens": 50,
                        "reasoning_output_tokens": 0,
                    },
                },
            )
            return

        self.send_error(404)

    @classmethod
    def _content_for_schema(cls, schema_name: str, user: str) -> object:
        cls.schema_names.append(schema_name)
        if schema_name == "athena_source_analysis_knowledge_extraction_v1":
            cls.extraction_calls += 1
            matches = re.findall(
                r"\[(\d+)\]\n(.*?)\n\[/EVIDENCE_\1\]",
                user,
                flags=re.DOTALL,
            )
            if not matches:
                raise AssertionError("missing evidence slot")
            sequence_text, evidence_text = matches[0]
            quote = evidence_text.strip()[:96]
            return {
                "knowledge_units": [],
                "claims": [
                    {
                        "source_sequence_no": int(sequence_text),
                        "source_quote": quote,
                        "claim_kind": "factual_assertion",
                        "statement": quote,
                        "epistemic_status": "asserted",
                        "confidence": 1.0,
                    }
                ],
                "relations": [],
                "merge_candidates": [],
            }
        if schema_name == "athena_source_extraction_semantic_dedup_v3":
            cls.merge_calls += 1
            return {"knowledge_duplicates": [], "claim_duplicates": []}
        if schema_name == "athena_source_extraction_pair_batch_audit_v1":
            cls.audit_calls += 1
            pair_numbers = [int(item) for item in re.findall(r"\[P(\d+)\]", user)]
            return {
                "assessments": [
                    {
                        "pair_no": pair_no,
                        "relationship": "compatible_or_unknown",
                        "confidence": 1.0,
                        "reason": "No contradiction established by the supplied pair.",
                    }
                    for pair_no in pair_numbers
                ]
            }
        if "map" in schema_name:
            return {
                "relevant": True,
                "summary": "Relevant source evidence.",
                "findings": ["Relevant finding."],
                "contradictions": [],
                "uncertainty": "",
            }
        return {
            "summary": "Synthesis of all relevant evidence.",
            "findings": ["Relevant finding."],
            "contradictions": [],
            "uncertainty": "",
        }

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_hierarchical_source_extraction_cli_batches_and_accepts_frozen_snapshot(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "runtime"
    source_file = tmp_path / "large-source.txt"
    source_file.write_text(
        "\n\n".join(
            f"FACT_{index:03d}: value {index}. " + (f"payload{index:03d} " * 130)
            for index in range(8)
        ),
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
    source_job = re.search(r"(?m)^Job:\s*(" + _UUID_RE.pattern + r")$", queued_source.stdout)
    assert source_job is not None
    processed = _run_cli(local_root, "job", "run-source", source_job.group(1))
    assert processed.returncode == 0, processed.stderr
    assert "Done: True" in processed.stdout

    _HierarchicalExtractionHandler.schema_names = []
    _HierarchicalExtractionHandler.extraction_calls = 0
    _HierarchicalExtractionHandler.merge_calls = 0
    _HierarchicalExtractionHandler.audit_calls = 0
    _HierarchicalExtractionHandler.native_payloads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HierarchicalExtractionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        queued_analysis = _run_cli(
            local_root,
            "job",
            "source-analyze",
            source_id,
            "Extract the substantive FACT values.",
            "--model",
            "fake-primary",
            "--context-limit",
            "3500",
            "--output-reserve",
            "400",
            "--safety-margin",
            "100",
            lm_studio_base_url=base_url,
        )
        assert queued_analysis.returncode == 0, queued_analysis.stderr
        analysis_job = re.search(r"(?m)^Job:\s*(" + _UUID_RE.pattern + r")$", queued_analysis.stdout)
        assert analysis_job is not None
        completed_analysis = _run_cli(
            local_root,
            "job",
            "run-analysis",
            analysis_job.group(1),
            lm_studio_base_url=base_url,
        )
        assert completed_analysis.returncode == 0, completed_analysis.stderr
        analysis_match = re.search(
            r"(?m)^Analysis:\s*(" + _UUID_RE.pattern + r")$",
            completed_analysis.stdout,
        )
        assert analysis_match is not None

        queued_extraction = _run_cli(
            local_root,
            "job",
            "source-extract",
            analysis_match.group(1),
            "--model",
            "fake-primary",
            "--context-limit",
            "3000",
            "--output-reserve",
            "500",
            "--safety-margin",
            "100",
            lm_studio_base_url=base_url,
        )
        assert queued_extraction.returncode == 0, queued_extraction.stderr
        extraction_job = re.search(
            r"(?m)^Job:\s*(" + _UUID_RE.pattern + r")$",
            queued_extraction.stdout,
        )
        assert extraction_job is not None
        assert '"pipeline_version":"source-analysis-knowledge-extraction/3"' in queued_extraction.stdout

        completed_extraction = _run_cli(
            local_root,
            "job",
            "run-extraction",
            extraction_job.group(1),
            lm_studio_base_url=base_url,
        )
        assert completed_extraction.returncode == 0, completed_extraction.stderr
        assert "State: completed" in completed_extraction.stdout
        assert "Done: True" in completed_extraction.stdout
        extraction_match = re.search(
            r"(?m)^Extraction:\s*(" + _UUID_RE.pattern + r")$",
            completed_extraction.stdout,
        )
        assert extraction_match is not None

        artifacts = _run_cli(
            local_root,
            "job",
            "extraction-artifacts",
            extraction_match.group(1),
            lm_studio_base_url=base_url,
        )
        assert artifacts.returncode == 0, artifacts.stderr
        assert "kind=batch" in artifacts.stdout
        assert "kind=merge" in artifacts.stdout
        assert "kind=audit" in artifacts.stdout
        final_match = re.search(
            r"(?m)^" + _UUID_RE.pattern + r" kind=final .* run=(" + _UUID_RE.pattern + r")$",
            artifacts.stdout,
        )
        assert final_match is not None
        frozen_run_id = final_match.group(1)
        assert _HierarchicalExtractionHandler.extraction_calls >= 2
        assert _HierarchicalExtractionHandler.merge_calls >= 1
        assert _HierarchicalExtractionHandler.audit_calls >= 1
        assert _HierarchicalExtractionHandler.native_payloads
        for index, payload in enumerate(_HierarchicalExtractionHandler.native_payloads):
            assert payload["reasoning"] == "off"
            if index == 0:
                assert payload["model"] == "fake-primary"
                assert payload["context_length"] == 3000
            else:
                assert payload["model"] == "fake-primary:runtime-1"
                assert "context_length" not in payload
            assert payload["max_output_tokens"] == 500
            assert payload["temperature"] == 0.0
            assert payload["top_p"] == 0.95
            assert payload["top_k"] == 40
            assert payload["min_p"] == 0.05
            assert payload["repeat_penalty"] == 1.1
            assert payload["stream"] is False
            assert payload["store"] is False
            assert "ATHENA_STRUCTURED_CONTRACT_VERSION: athena.controlled_structured_json/1" in str(
                payload["system_prompt"]
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    accepted = _run_cli(
        local_root,
        "extract",
        "accept-source-run",
        frozen_run_id,
        input_text="y\n",
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "Loaded frozen source extraction proposal snapshot; Primary Model was not called." in accepted.stdout
    assert "Claims resolved:" in accepted.stdout

    database = sqlite3.connect(local_root / "state" / "athena.db")
    try:
        state, total_batches, completed_batches = database.execute(
            "SELECT state, total_batches, completed_batches FROM source_extractions"
        ).fetchone()
        assert state == "completed"
        assert total_batches >= 2
        assert completed_batches == total_batches
        assert database.execute("SELECT COUNT(*) FROM claims").fetchone()[0] >= 2
        assert database.execute(
            "SELECT COUNT(*) FROM source_extraction_result_snapshots"
        ).fetchone()[0] == 1
    finally:
        database.close()
