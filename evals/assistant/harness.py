"""Build a world (API services over the synthetic fixtures) and drive the assistant against it."""
from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kalmora.app.container import Services, Settings
from kalmora.assistant.loop import Assistant, ChatRequest, DEEP, FAST, Limits
from kalmora.assistant.model import AgentModel
from kalmora.assistant.tools import McpMemorySource
from kalmora.mcp.server import create_server

from . import fixtures


class World:
    """Services + loaded synthetic phase + run bundles, in a temp directory. Use as a context manager."""

    def __init__(self, inject: dict[str, str] | None = None, policy: str = fixtures.POLICY, runs: bool = True,
                 archive: bytes | None = None, phase: str = fixtures.PHASE) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "runs"
        self.run_dir.mkdir()
        self.services = Services(Settings(data_dir=self.root / "data", run_dir=self.run_dir, submissions_dir=self.root / "subs"))
        archive_path = self.root / "phase.zip"
        archive_path.write_bytes(archive if archive is not None else fixtures.build_zip(inject, policy, phase))
        envelope, created = self.services.ingest.start(archive_path)
        assert created, envelope
        self.services.ingest.run(envelope["data"]["job_id"])
        job = self.services.get_job(envelope["data"]["job_id"])["data"]
        assert job["status"] == "loaded", job
        self.runs = fixtures.make_runs(self.run_dir, inject) if runs else {}

    def source(self) -> McpMemorySource:
        return McpMemorySource(create_server(self.services))

    def assistant(self, model: AgentModel, fast: AgentModel | None = None, *, limits: dict[str, Limits] | None = None,
                  **kwargs: Any) -> Assistant:
        return Assistant(models={"deep": model, "fast": fast or model}, source=self.source(),
                         limits=limits or {"fast": FAST, "deep": DEEP}, today=lambda: "2026-10-03", **kwargs)

    def close(self) -> None:
        self.services.close()
        self._tmp.cleanup()

    def __enter__(self) -> "World":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass
class Answer:
    events: list[dict[str, Any]] = field(default_factory=list)

    def of(self, name: str) -> list[Any]:
        return [e["data"] for e in self.events if e["event"] == name]

    @property
    def text(self) -> str:
        return "".join(d["text"] for d in self.of("delta"))

    @property
    def cards(self) -> list[dict[str, Any]]:
        return self.of("card")

    @property
    def citations(self) -> list[dict[str, Any]]:
        return self.of("citation")

    @property
    def error(self) -> str | None:
        errors = self.of("error")
        return errors[0] if errors else None

    @property
    def done(self) -> dict[str, Any] | None:
        done = self.of("done")
        return done[0] if done else None

    @property
    def order(self) -> list[str]:
        return [e["event"] for e in self.events]


async def collect_async(assistant: Assistant, request: ChatRequest) -> Answer:
    return Answer([event async for event in assistant.answer(request)])


def ask(assistant: Assistant, question: str, *, mode: str = "deep", run: str | None = None, dataset: str | None = fixtures.PHASE,
        history: list[dict[str, str]] | None = None) -> Answer:
    request = ChatRequest(messages=[*(history or []), {"role": "user", "content": question}], mode=mode, run_id=run, dataset_id=dataset)
    return asyncio.run(collect_async(assistant, request))
