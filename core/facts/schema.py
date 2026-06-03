"""Pydantic models for the per-user durable memory document."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FactEntry(BaseModel):
    cardinality: Literal["single", "multi"] = "single"
    value: str | list[str]
    confidence: float = 0.5
    source: str | None = None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None


class SupersededEntry(BaseModel):
    key: str
    value: str | list[str]
    retired_at: datetime
    reason: str | None = None


class UserMemoryDocument(BaseModel):
    user_id: str
    schema_version: int = 1
    rolling_summary: str = ""
    summary_updated_at: datetime | None = None
    facts: dict[str, FactEntry] = Field(default_factory=dict)
    superseded: list[SupersededEntry] = Field(default_factory=list)

    @classmethod
    def empty(cls, user_id: str) -> "UserMemoryDocument":
        return cls(user_id=user_id)

    def to_json(self) -> dict:
        return self.model_dump(mode="json")
