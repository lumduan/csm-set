"""Project-wide constants for csm-set."""

# TradingView symbol format used by tvkit
SET_INDEX_SYMBOL: str = "SET:SET"

# SET industry group codes
SET_SECTOR_CODES: list[str] = [
    "AGRO",
    "CONSUMP",
    "FINCIAL",
    "INDUS",
    "PROPCON",
    "RESOURC",
    "SERVICE",
    "TECH",
]

# Rebalance schedule - pandas month-end offset alias
REBALANCE_FREQUENCY: str = "ME"

# Jegadeesh-Titman default parameters
DEFAULT_LOOKBACK_MONTHS: int = 12
DEFAULT_SKIP_MONTHS: int = 1
DEFAULT_TOP_QUANTILE: float = 0.2

# Universe screening thresholds
MIN_PRICE_THRESHOLD: float = 1.0  # THB - exclude penny stocks
MIN_AVG_DAILY_VOLUME: float = 1_000_000.0  # THB - minimum liquidity
MIN_DATA_COVERAGE: float = 0.80  # 80% non-NaN required in lookback window

# Transaction cost (one-way, basis points)
TRANSACTION_COST_BPS: float = 15.0

# Timezone for all timestamps and scheduler jobs
TIMEZONE: str = "Asia/Bangkok"

# Risk-free rate assumption (Thai 1-year government bond approximate)
RISK_FREE_RATE_ANNUAL: float = 0.02

__all__: list[str] = [
    "DEFAULT_LOOKBACK_MONTHS",
    "DEFAULT_SKIP_MONTHS",
    "DEFAULT_TOP_QUANTILE",
    "MIN_AVG_DAILY_VOLUME",
    "MIN_DATA_COVERAGE",
    "MIN_PRICE_THRESHOLD",
    "REBALANCE_FREQUENCY",
    "RISK_FREE_RATE_ANNUAL",
    "SET_INDEX_SYMBOL",
    "SET_SECTOR_CODES",
    "TIMEZONE",
    "TRANSACTION_COST_BPS",
]