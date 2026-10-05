from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import requests

from .assertions import AssertionEngine, AssertionResult
from .context import RunContext
from .extractors import ExtractionResult, ExtractorEngine
from .request_builder import RequestBuilder, RequestSpec


@dataclass
class RunResult:
    request: RequestSpec | None
    response: Any = None
    response_time_ms: float | None = None
    assertions: list[AssertionResult] = field(default_factory=list)
    extractions: list[ExtractionResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and all(item.passed for item in self.assertions)
            and all(item.success for item in self.extractions if item.required)
        )

    def response_snapshot(self) -> dict[str, Any] | None:
        if self.response is None:
            return None
        payload = None
        try:
            payload = self.response.json()
        except (ValueError, TypeError):
            pass
        return {
            'headers': dict(self.response.headers),
            'body': self.response.text,
            'json': payload,
        }


class ApiRunner:
    def __init__(
        self,
        *,
        http_client: Any = requests,
        request_builder: RequestBuilder | None = None,
        assertion_engine: AssertionEngine | None = None,
        extractor_engine: ExtractorEngine | None = None,
        clock: Any = time.perf_counter,
    ) -> None:
        self.http_client = http_client
        self.request_builder = request_builder or RequestBuilder()
        self.assertion_engine = assertion_engine or AssertionEngine()
        self.extractor_engine = extractor_engine or ExtractorEngine()
        self.clock = clock

    def run(
        self,
        definition: Mapping[str, Any],
        context: RunContext,
        *,
        assertions: Iterable[Mapping[str, Any]] | None = None,
        extractors: Iterable[Mapping[str, Any]] | None = None,
    ) -> RunResult:
        spec: RequestSpec | None = None
        try:
            spec = self.request_builder.build(definition, context)
            started = self.clock()
            response = self.http_client.request(**spec.request_kwargs())
            duration = (self.clock() - started) * 1000
            assertion_results = self.assertion_engine.evaluate(
                response,
                assertions,
                response_time_ms=duration,
            )
            extraction_results = self.extractor_engine.extract(response, extractors, context)
            return RunResult(spec, response, duration, assertion_results, extraction_results)
        except Exception as exc:
            return RunResult(spec, error=str(exc))
