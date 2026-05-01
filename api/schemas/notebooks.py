"""Notebook index response schemas.

Full implementation lands in Phase 5.6.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NotebookEntry(BaseModel):
    """A single published analysis notebook."""

    name: str = Field(description="Notebook file name")
    path: str = Field(description="URL path component")
    size_bytes: int = Field(ge=0, description="File size in bytes")
    last_modified: str = Field(description="ISO-8601 last-modified timestamp")


class NotebookIndex(BaseModel):
    """List of available published notebooks."""

    items: list[NotebookEntry] = Field(description="Available notebooks")
