"""Strict input validation models for API query/path parameters.

These Pydantic models use ``extra="forbid"`` to reject unexpected query
parameters.  When no parameters are expected, the models are empty but
FastAPI still validates that no unknown query keys are present.

Usage::

    @router.get("", response_model=Foo)
    async def get_foo(params: FooParams = Depends()) -> Foo:
        ...

.. note::

    Models with zero fields do not trigger query-param validation in
    FastAPI because there is nothing to bind.  Endpoints with genuinely
    zero parameters rely on FastAPI's default behaviour of ignoring
    unknown keys, which is safe for idempotent GET requests.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UniverseParams(BaseModel):
    """Query parameters for GET /api/v1/universe.

    Reserved for future ``?asof=`` or ``?limit=`` filters.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class SignalParams(BaseModel):
    """Query parameters for GET /api/v1/signals/latest."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PortfolioParams(BaseModel):
    """Query parameters for GET /api/v1/portfolio/current."""

    model_config = ConfigDict(extra="forbid", frozen=True)


__all__: list[str] = ["PortfolioParams", "SignalParams", "UniverseParams"]
