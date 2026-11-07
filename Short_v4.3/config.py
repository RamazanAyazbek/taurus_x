# Taurus SHORT v4 — confirmation TakerBuy filter experiment.
SYMBOL = "BTCUSDT"
LOG_FILE = "data/taurus_x_container.log"
RESULTS_DIR = "results"
RESULT_PREFIX = "short"
STRATEGY_VERSION = "v7.4.ch.3add"

# Keep the Long project's TP/SL, fee model, and timeout logic.
TP_PCT = 1.5
SL_PCT = 0.7
TIMEOUT_MINUTES = 1080
TAKER_FEE = 0.05
MAKER_FEE = 0.02
ENABLE_FEES = True
ENABLE_STATE_LOCK = True

# Wait for the next Taurus monitoring observation before entry.
# If price has bounced too far upward against the SHORT idea, cancel it.
# If confirmed, the simulator enters at the next observation's price/time.
ENTRY_CONFIRMATION_ENABLED = True
CONFIRMATION_MAX_GAP_MINUTES = 20
CONFIRMATION_MAX_REBOUND_PCT = 0.25

# New v4 filter: at confirmation, require TakerBuy >= this threshold.
# Hypothesis: avoid chasing a sell impulse when aggressive selling dominates.
# Exploratory only; validate on fresh periods before using live.
CONFIRMATION_MIN_TAKER_BUY = 42.0

# Base SHORT-entry filters.
MIN_VOLUME_XMED = 1.5
MIN_DOI_XMED = 0.0
MAX_DOI_XMED = 6.0
MIN_D_OI = 0.30
MAX_TAKER_BUY = 45.0
MAX_CURRENT_DPRICE = -0.10
MAX_PREVIOUS_30M_RETURN = -0.05
MAX_PREVIOUS_2H_RETURN = -0.15
MAX_PREVIOUS_4H_RETURN = -0.30

# Regime brake: don't open SHORT in a clear higher-timeframe bullish market.
# Both returns must meet their thresholds to classify the regime as bullish.
BULL_FILTER_ENABLED = True
BULL_12H_RETURN_MIN = 0.40
BULL_24H_RETURN_MIN = 0.80

# Exhaustion brake: avoid shorting after a climactic sell-off with abnormally
# high volume. Thresholds use only data available at signal time.
CLIMAX_FILTER_ENABLED = True
CLIMAX_MIN_VOLUME_XMED = 6.0
CLIMAX_MAX_30M_RETURN = -0.45
CLIMAX_MAX_CURRENT_DPRICE = -0.45


# Optional confirmation-quality experiments (disabled by default to preserve
# the current v6.ch baseline until each experiment is run and compared).
# A) Reject confirmation records where aggressive buying is too strong.
CONFIRMATION_MAX_TAKER_BUY_ENABLED = True
CONFIRMATION_MAX_TAKER_BUY = 60.0

# B) Require price to resume moving down before entering SHORT.
# Example: 0.02 means confirmation price must be at least 0.02% below
# the signal price. This would reject the 2026-10-26 case (+0.178%).
CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED = False
CONFIRMATION_MIN_DOWN_MOVE_PCT = 0.02


# ===== THREE ADDITIONS (backtest only; switches are independent) =====
# All 3 are enabled for the new combined run. Turn any one OFF to compare.
# These are hypothetical position-size multipliers, NOT live Binance orders.
# They do not reject qualified signals and do not change TP=1.5 / SL=0.7.

# 1) Reduce size if the entry is inside or <=0.35% above a recently logged S1.
SUPPORT_RISK_ENABLED = True
SUPPORT_LOOKBACK_MINUTES = 60
SUPPORT_NEAR_PCT = 0.35
SUPPORT_SIZE_MULTIPLIER = 0.50

# 2) Reduce size if TakerBuy grew >=7 percentage points in last ~20m.
TAKER_RISE_RISK_ENABLED = True
TAKER_LOOKBACK_MINUTES = 20
TAKER_LOOKBACK_MAX_STALENESS_MINUTES = 10
TAKER_RISE_THRESHOLD_PP = 7.0
TAKER_SIZE_MULTIPLIER = 0.50

# 3) Model entry 3m AFTER confirmation at Binance 1m OPEN; if the price
# fell >=0.20% during that delay, reduce size (do not reject the signal).
PREENTRY_CHECK_ENABLED = True
PREENTRY_DELAY_MINUTES = 3
PREENTRY_FALL_THRESHOLD_PCT = 0.20
PREENTRY_SIZE_MULTIPLIER = 0.50

# Floor when several signals reduce position size at the same time.
MIN_SIZE_MULTIPLIER = 0.25
