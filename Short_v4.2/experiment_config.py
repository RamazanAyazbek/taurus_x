"""Research-only settings. Original config.py is intentionally NOT changed.

Run `python run_experiments.py` to compare five independent simulations.
Values are exploration defaults, not optimized thresholds.
"""

# A — Support proximity: reduce theoretical position size, do NOT reject entry.
SUPPORT_LOOKBACK_MINUTES = 60
SUPPORT_NEAR_PCT = 0.35    # % above S1 upper band (within S1 also counts)
SUPPORT_SIZE_MULTIPLIER = 0.50

# B — TakerBuy acceleration: compare confirmation to monitor reading ~20m ago.
TAKER_LOOKBACK_MINUTES = 20
TAKER_LOOKBACK_MAX_STALENESS_MINUTES = 10
TAKER_RISE_THRESHOLD_PP = 7.0   # percentage POINTS, not percent return
TAKER_SIZE_MULTIPLIER = 0.50

# C — Approximate live decision delay: use Binance Futures 1m OPEN at t+3m.
# All C trades are re-priced. If the price declined >= threshold, size is reduced.
# This is a hypothetical executable entry at 1m OPEN, not an actual Binance fill.
PREENTRY_DELAY_MINUTES = 3
PREENTRY_FALL_THRESHOLD_PCT = 0.20
PREENTRY_SIZE_MULTIPLIER = 0.50

# Combined mode: multiply applicable sizes but do not go below this fraction.
COMBINED_MIN_SIZE_MULTIPLIER = 0.25

# The baseline TP/SL, commission and all signal filters are read from config.py.
# The source close/timeout simulator is unchanged and still ignores the first 1m candle.
