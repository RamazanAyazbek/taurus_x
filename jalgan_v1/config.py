# Taurus Backtest V5.7 — experimental filters and break-even execution model
TP_PCT = 1.5
SL_PCT = 0.7
BE_PCT = 1.1              # favorable excursion needed to activate break-even stop
TIMEOUT_MINUTES = 1080
TAKER_FEE = 0.05          # percent per side
MAKER_FEE = 0.02          # percent per side, used for TP exits

SYMBOL = "BTCUSDT"
LOG_FILE = "data/taurus_x_container.log"
OUTPUT_CSV = "data/backtest_details_v5.7.csv"

ENABLE_MOVEMENT_PROFILE = True
ENABLE_OI_FEATURES = True
ENABLE_PREVIOUS_2H_4H = True
ENABLE_PREVIOUS_30M = True
ENABLE_STATE_LOCK = True
ENABLE_FEES = True

# Original V5 filters
VOLUME_XMED_MIN = 0.5
VOLUME_MIN = 7200
OI_XMED_MAX = 6.0
CURRENT_DOI_MIN = 0.30
CURRENT_VOLUME_XMED_MIN = 1.8  # first change being tested
PREVIOUS_4H_RETURN_MAX = 2.0
PREVIOUS_2H_RETURN_MIN = 0.0
PREVIOUS_30M_RETURN_MAX = 0.8
TAKER_BUY_MAX = 64

# Experiment A: require positive price momentum over the latest ~10-minute interval.
ENABLE_SHORT_TERM_MOMENTUM_FILTER = True
MOMENTUM_LOOKBACK_MINUTES = 10
MOMENTUM_MIN_RETURN_PCT = 0.0  # strictly positive; value must be > this threshold
MOMENTUM_MAX_LOOKBACK_GAP_MINUTES = 20  # reject stale/missing comparison data

# Experiment B: if price is inside a logged R1 resistance zone, only allow a
# LONG after a prior breakout above that zone and a retest near its upper edge.
ENABLE_R1_BREAKOUT_RETEST_FILTER = True
R1_RETEST_LOOKBACK_MINUTES = 120
R1_RETEST_TOLERANCE_PCT = 0.15

# Regime diagnostic / optional filter. Disabled by default so the first runs isolate
# momentum + R1 + BE effects. Set True to require non-negative 4h return for LONG.
ENABLE_4H_BULL_REGIME_FILTER = False
PREVIOUS_4H_RETURN_MIN = 0.0

# Optional experimental short strategy. Disabled by default; needs separate validation.
ENABLE_SHORT_SIGNALS = False
SHORT_PREVIOUS_4H_RETURN_MAX = 0.0
SHORT_PREVIOUS_2H_RETURN_MAX = 0.0
SHORT_PREVIOUS_30M_RETURN_MIN = -0.8
SHORT_TAKER_BUY_MIN = 36.0

PROFILE_HORIZONS = (10, 20, 30, 60, 120, 240, 360, 720, 1080)
