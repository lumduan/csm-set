"""Square-root market-impact slippage model.

Formula (PLAN.md §4.7):
    slippage_bps = half_spread_bps + impact_coef × sqrt(participation_rate)

Zero if notional ≤ 0 or ADTV ≤ 0.
"""

import math

from pydantic import BaseModel, Field


class SlippageModelConfig(BaseModel):
    """Configuration for the sqrt-impact slippage model.

    Defaults are conservative for SET mid/large-caps (PLAN.md §4.7).
    """

    half_spread_bps: float = Field(default=10.0, ge=0.0)
    impact_coef: float = Field(default=10.0, ge=0.0)


class SqrtImpactSlippageModel:
    """Square-root market-impact slippage model (Almgren–Chriss-inspired).

    This is a stateless utility.  Config is injected at construction.
    """

    def __init__(self, config: SlippageModelConfig | None = None) -> None:
        self._config: SlippageModelConfig = config or SlippageModelConfig()

    def estimate(self, notional_thb: float, adtv_thb: float) -> float:
        """Return estimated slippage in basis points.

        Returns 0.0 when notional ≤ 0 or ADTV is zero / invalid.
        """
        if notional_thb <= 0.0 or adtv_thb <= 0.0:
            return 0.0

        participation_rate: float = notional_thb / adtv_thb
        impact: float = self._config.impact_coef * math.sqrt(participation_rate)
        return self._config.half_spread_bps + impact


__all__: list[str] = [
    "SlippageModelConfig",
    "SqrtImpactSlippageModel",
]
