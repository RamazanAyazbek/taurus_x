"""LONG V2 research config: rising-regime entry filters + faster strict backtest."""

# Trade management. BE is implemented as an optional switch but left OFF so the
# first V2 run isolates entry-filter changes from exit-management changes.
TP_PCT = 1.5
SL_PCT = 0.7
BE_PCT = 1.1
ENABLE_BREAKEVEN = False
TIMEOUT_MINUTES = 1080
TAKER_FEE = 0.05
MAKER_FEE = 0.02

SYMBOL = "BTCUSDT"
LOG_FILE = "data/taurus_x_container.log"
OUTPUT_CSV = "data/backtest_details_v6.6csv"

ENABLE_MOVEMENT_PROFILE = False
ENABLE_OI_FEATURES = False
ENABLE_PREVIOUS_2H_4H = True
ENABLE_PREVIOUS_30M = True
ENABLE_STATE_LOCK = True
ENABLE_FEES = True

# Legacy broad checks. CURRENT_VOLUME_XMED_MIN is the effective volume-ratio gate.
VOLUME_XMED_MIN = 0.5
VOLUME_MIN = 7200
OI_XMED_MAX = 6.0
CURRENT_DOI_MIN = 0.30
CURRENT_VOLUME_XMED_MIN = 2.0  # candidate change: was 1.8; reject barely-qualified activity

# Short-term direction checks. LONG entries are not allowed if the 4h return is negative.
PREVIOUS_4H_RETURN_MIN = 0.0
PREVIOUS_4H_RETURN_MAX = 2.0
PREVIOUS_2H_RETURN_MIN = 0.0
PREVIOUS_30M_RETURN_MAX = 0.8
TAKER_BUY_MAX = 64

# New long-specific filters. Each can be toggled independently for ablation testing.
ENABLE_LONG_TREND_FILTER = True
LONG_TREND_SMA_HOURS = 12
LONG_TREND_SLOPE_LOOKBACK_HOURS = 2
LONG_TREND_MIN_SMA_SLOPE_PCT = 0.02  # 12h SMA must rise >0.02% over the last 2h
LONG_TREND_MAX_STALE_MINUTES = 20
ENABLE_LONG_R1_REJECTION = True       # do not buy into the logged R1 resistance area

# Lookback freshness: maximum age of the observation used for each lookback.
LONG_MAX_AGE_30M = 45
LONG_MAX_AGE_2H = 150
LONG_MAX_AGE_4H = 270
LONG_MAX_AGE_12H = 750
LONG_MAX_AGE_48H = 2940

PROFILE_HORIZONS = (10, 20, 30, 60, 120, 240, 360, 720, 1080)
