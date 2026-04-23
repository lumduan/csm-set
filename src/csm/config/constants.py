"""Project-wide constants for csm-set."""

# TradingView symbol format used by tvkit
INDEX_SYMBOL: str = "SET:SET"

# SET industry group codes → official English names (source: SET website)
SET_SECTOR_CODES: dict[str, str] = {
    "AGRO": "Agro & Food Industry",
    "CONSUMP": "Consumer Products",
    "FINCIAL": "Financials",
    "INDUS": "Industrials",
    "PROPCON": "Property & Construction",
    "RESOURC": "Resources",
    "SERVICE": "Services",
    "TECH": "Technology",
}

# Rebalance schedule - pandas business month-end offset alias
REBALANCE_FREQ: str = "BME"

# History depth for full backtest
LOOKBACK_YEARS: int = 15

# Jegadeesh-Titman default parameters
DEFAULT_LOOKBACK_MONTHS: int = 12
DEFAULT_SKIP_MONTHS: int = 1
DEFAULT_TOP_QUANTILE: float = 0.2

# Universe screening thresholds
MIN_PRICE_THB: float = 1.0  # THB - exclude penny stocks
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
    "INDEX_SYMBOL",
    "LOOKBACK_YEARS",
    "MIN_AVG_DAILY_VOLUME",
    "MIN_DATA_COVERAGE",
    "MIN_PRICE_THB",
    "REBALANCE_FREQ",
    "RISK_FREE_RATE_ANNUAL",
    "SET_SECTOR_CODES",
    "TIMEZONE",
    "TRANSACTION_COST_BPS",
]
