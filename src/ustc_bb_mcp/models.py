"""Shared data contract for parsers, service and MCP tools."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def checked_at() -> str:
    return datetime.now(UTC).isoformat()


class Course(BaseModel):
    id: str
    name: str
    url: str
    term: str | None = None


class CourseFile(BaseModel):
    id: str
    course_id: str
    name: str
    url: str
    source_url: str
    date: str | None = None


class Assignment(BaseModel):
    id: str
    course_id: str
    name: str
    url: str
    kind: Literal["assignment", "test"] = "assignment"
    due_at: str | None = None
    due_text: str | None = None
    status: Literal["not_submitted", "draft", "submitted", "graded", "unknown"] = "unknown"
    grade: str | None = None
    requirements: str = ""
    attachments: list[CourseFile] = Field(default_factory=list)


class Announcement(BaseModel):
    id: str
    course_id: str
    title: str
    body: str
    url: str
    date: str | None = None


class ContentPage(BaseModel):
    files: list[CourseFile] = Field(default_factory=list)
    assignments: list[Assignment] = Field(default_factory=list)
    folders: list[str] = Field(default_factory=list)


class Result(BaseModel):
    ok: bool = True
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    complete: bool = True
    warnings: list[str] = Field(default_factory=list)
    checked_at: str = Field(default_factory=checked_at)
    error: dict[str, Any] | None = None
