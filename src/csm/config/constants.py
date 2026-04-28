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
MIN_AVG_DAILY_VOLUME: float = 1_000_000.0  # THB - minimum liquidity (universe pre-filter)
MIN_DATA_COVERAGE: float = 0.80  # 80% non-NaN required in lookback window

# Hard ADTV gate applied inside the backtest engine before ranking
MIN_ADTV_63D_THB: float = 5_000_000.0  # 5 M THB 63-day value turnover (close × volume)

# Market timing filter
EMA_TREND_WINDOW: int = 200  # EMA span for bull/bear regime detection

# Safe Mode allocation (SET < EMA 200)
SAFE_MODE_MAX_EQUITY: float = 0.20  # max equity fraction; remainder is cash

# Bull Mode portfolio size
BULL_MODE_N_HOLDINGS_MIN: int = 80
BULL_MODE_N_HOLDINGS_MAX: int = 100

# Buffer logic — only evict a holding when new candidate ranks this many percentile points better
BUFFER_RANK_THRESHOLD: float = 0.125  # midpoint of 10–15% band

# Transaction cost (one-way, basis points)
TRANSACTION_COST_BPS: float = 15.0

# Timezone for all timestamps and scheduler jobs
TIMEZONE: str = "Asia/Bangkok"

# Risk-free rate assumption (Thai 1-year government bond approximate)
RISK_FREE_RATE_ANNUAL: float = 0.02

__all__: list[str] = [
    "BUFFER_RANK_THRESHOLD",
    "BULL_MODE_N_HOLDINGS_MAX",
    "BULL_MODE_N_HOLDINGS_MIN",
    "DEFAULT_LOOKBACK_MONTHS",
    "DEFAULT_SKIP_MONTHS",
    "DEFAULT_TOP_QUANTILE",
    "EMA_TREND_WINDOW",
    "INDEX_SYMBOL",
    "LOOKBACK_YEARS",
    "MIN_ADTV_63D_THB",
    "MIN_AVG_DAILY_VOLUME",
    "MIN_DATA_COVERAGE",
    "MIN_PRICE_THB",
    "REBALANCE_FREQ",
    "RISK_FREE_RATE_ANNUAL",
    "SAFE_MODE_MAX_EQUITY",
    "SET_SECTOR_CODES",
    "TIMEZONE",
    "TRANSACTION_COST_BPS",
]
