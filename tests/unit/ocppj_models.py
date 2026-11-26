"""Hand-written messages used to test the registry and endpoint before generation exists."""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class HeartbeatRequest(Base):
    ACTION: ClassVar[str] = "Heartbeat"


class HeartbeatResponse(Base):
    ACTION: ClassVar[str] = "Heartbeat"
    current_time: datetime


class EchoRequest(Base):
    ACTION: ClassVar[str] = "Echo"
    text: str = Field(min_length=1, max_length=10)
    count: int | None = None
    items: list[int] | None = Field(default=None, min_length=1, max_length=3)
    when: datetime | None = None


class EchoResponse(Base):
    ACTION: ClassVar[str] = "Echo"
    text: str
