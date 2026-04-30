"""Universe response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UniverseItem(BaseModel):
    """A single security in the stored universe.

    Extra DataFrame columns (asof, sector, etc.) are accepted silently.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    symbol: str = Field(description="Ticker symbol (e.g. SET:AOT)")


class UniverseSnapshot(BaseModel):
    """Current stored universe snapshot."""

    model_config = ConfigDict(frozen=True)

    items: list[UniverseItem] = Field(description="List of universe constituents")
    count: int = Field(description="Number of items in the snapshot")
