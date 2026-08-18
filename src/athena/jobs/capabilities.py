"""Fail-closed durable-job execution capability classification."""

from __future__ import annotations

# Only jobs proven not to call the local model/provider belong here.
# Any new/unknown job type remains provider-isolated until explicitly reviewed.
CONTROL_LANE_JOB_TYPES = frozenset(
    {
        "source.process",
        "backup.create",
        "archive.replicate",
    }
)


def requires_provider_isolation(job_type: str) -> bool:
    """Return True unless a durable job is explicitly classified control-safe."""
    return job_type not in CONTROL_LANE_JOB_TYPES
