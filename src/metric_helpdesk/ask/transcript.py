"""Save and replay ask sessions, so the API path can be shown and tested without credentials.

A transcript holds the question and each API response in order. Replay hands those responses
back while the tools still run for real against the local warehouse.
"""

import json
from pathlib import Path
from typing import Any, Literal

from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, Field

from metric_helpdesk.ask.loop import MessagesClient


class TranscriptError(ValueError):
    """Raised when a transcript is missing, malformed or does not match the question."""


class Transcript(BaseModel):
    """A saved ask session. ``source`` says whether it came from the real API."""

    source: Literal["recorded", "hand-built fixture"]
    question: str
    model: str
    responses: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        if not path.is_file():
            raise TranscriptError(f"Transcript not found: {path}")
        return cls.model_validate_json(path.read_text())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2) + "\n")


class RecordingClient:
    """Passes calls to a real client and keeps every response."""

    def __init__(self, inner: MessagesClient, question: str, model: str) -> None:
        self._inner = inner
        self.transcript = Transcript(source="recorded", question=question, model=model)

    async def create(self, **params: Any) -> Any:
        response = await self._inner.create(**params)
        self.transcript.responses.append(response.model_dump(mode="json"))
        return response


class ReplayClient:
    """Returns saved responses in order instead of calling the API."""

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self._next = 0

    def check_question(self, question: str) -> None:
        if question.strip() != self.transcript.question.strip():
            raise TranscriptError(
                f"This transcript answers {self.transcript.question!r}, not {question!r}."
            )

    async def create(self, **params: Any) -> BetaMessage:
        if self._next >= len(self.transcript.responses):
            raise TranscriptError("Transcript ran out of responses; the session diverged.")
        response = BetaMessage.model_validate(self.transcript.responses[self._next])
        self._next += 1
        return response
