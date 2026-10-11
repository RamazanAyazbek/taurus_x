"""Shared backtest/execution settings for Taurus Backtest V5.8."""

# Select exactly what to evaluate: "LONG", "SHORT", or "BOTH".
# SHORT is the default so the first run studies the isolated short hypotheses.
BACKTEST_SIDE = "SHORT"
# If BOTH directions fire on the same observation: "SKIP", "LONG", or "SHORT".
BOTH_SIGNAL_CONFLICT_POLICY = "SKIP"

SYMBOL = "BTCUSDT"
LOG_FILE = "data/taurus_x_container.log"
OUTPUT_CSV = "data/short-r1-confirmed-strict.csv"

# Shared trade/execution model. Percentages are price-move percentages, not account returns.
TP_PCT = 1.5
SL_PCT = 0.7
BE_PCT = 1.1
TIMEOUT_MINUTES = 1080
TAKER_FEE = 0.05  # percent per side
MAKER_FEE = 0.02  # percent per side for TP exits
ENABLE_FEES = True

# Shared diagnostics. Movement profile uses the downloaded 1m OHLC candles.
ENABLE_MOVEMENT_PROFILE = True
ENABLE_OI_FEATURES = True
PROFILE_HORIZONS = (10, 20, 30, 60, 120, 240, 360, 720, 1080)

# Applies to the legacy LONG strategy's signal-state lock only.
ENABLE_STATE_LOCK = True
