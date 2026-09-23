"""Test doubles. The langchain fake chat models do not implement structured output usefully."""

from typing import Any

from jobscout.matching.schemas import EvaluationResult


class _StructuredRunnable:
    def __init__(self, parent: "CountingChatModel") -> None:
        self._parent = parent

    def invoke(self, _messages: Any) -> EvaluationResult:
        self._parent.calls += 1
        if self._parent.error is not None:
            raise self._parent.error
        index = min(self._parent.calls - 1, len(self._parent.results) - 1)
        return self._parent.results[index]


class CountingChatModel:
    """Counts `.invoke` calls so a test can prove the LLM was skipped."""

    def __init__(
        self, results: list[EvaluationResult] | None = None, error: Exception | None = None
    ) -> None:
        self.results = results or [
            EvaluationResult(
                score=75,
                reasoning="Good overlap on Python and LLM work.",
                matched_skills=["Python"],
                missing_skills=["Kubernetes"],
                red_flags=[],
            )
        ]
        self.error = error
        self.calls = 0

    def with_structured_output(self, _schema: Any) -> _StructuredRunnable:
        return _StructuredRunnable(self)
