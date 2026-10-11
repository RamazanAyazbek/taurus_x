"""SHORT-only hypotheses and independent, editable thresholds.

All return thresholds below are in percentage points, e.g. -0.03 means -0.03%.
Each hypothesis can be enabled/disabled independently. Start by running them one at a time.
"""

# Hypothesis switches. Run one hypothesis at a time.
# The default is the STRICT confirmed R1 variant after fixing the unbounded-high bug.
# This is an experiment, not a validated profitable strategy.
ENABLE_SHORT_TREND_CONTINUATION = False
ENABLE_SHORT_R1_REJECTION = False
ENABLE_SHORT_R1_CONFIRMED_REJECTION = True
ENABLE_SHORT_PUMP_REVERSAL = False  # Research candidate; test separately from R1.
ENABLE_SHORT_OI_UNWIND_DOWNTURN = False  # Rare event-study pattern; validate separately.
ENABLE_SHORT_S1_BREAKDOWN = False

# Prevent repeated entries on consecutive log snapshots for the same SHORT research stream.
SHORT_REENTRY_COOLDOWN_MINUTES = 180

# Historical feature freshness. Missing/stale history rejects the signal rather than guessing.
SHORT_LOOKBACK_10M = 10
SHORT_LOOKBACK_30M = 30
SHORT_LOOKBACK_60M = 60
SHORT_LOOKBACK_2H = 120
SHORT_LOOKBACK_4H = 240
SHORT_MAX_GAP_10M = 20
SHORT_MAX_GAP_30M = 45
SHORT_MAX_GAP_60M = 80
SHORT_MAX_GAP_2H = 150
SHORT_MAX_GAP_4H = 270

# Optional activity / OI filters are independent for each hypothesis. The log has both projected
# and within-hour cumulative volume ratios, so these are OFF by default for the first clean test.
# Turn them on in a later ablation run to see if they genuinely help.

# H1 — Trend continuation. Current scan suggests this is a weak/possibly adverse SHORT premise.
SHORT_TREND_4H_MAX_RETURN_PCT = -0.30
SHORT_TREND_2H_MAX_RETURN_PCT = -0.15
SHORT_TREND_10M_MAX_RETURN_PCT = -0.05
SHORT_TREND_USE_TAKER_FILTER = False
SHORT_TREND_MAX_TAKER_BUY = 45.0
SHORT_TREND_USE_ACTIVITY_FILTER = False
SHORT_TREND_MIN_VOL_XMED = 1.5
SHORT_TREND_USE_DOI_XMED_FILTER = False
SHORT_TREND_MAX_DOI_XMED = 6.0

# H2 — Simple R1 rejection (the original baseline hypothesis):
# price is in the upper half of a logged R1 zone, short-term returns turn down,
# and the buyer fraction is not dominant. The current sample is only ~10 observations.
SHORT_R1_MIN_ZONE_POSITION = 0.50  # 0=zone bottom, 1=zone top
SHORT_R1_MAX_ZONE_POSITION = 1.00  # above the top is treated as possible breakout, not a fade
SHORT_R1_MAX_RETURN_10M_PCT = -0.03
SHORT_R1_MAX_RETURN_30M_PCT = 0.00
SHORT_R1_USE_TAKER_FILTER = True
SHORT_R1_MAX_TAKER_BUY = 50.0
SHORT_R1_USE_ACTIVITY_FILTER = False
SHORT_R1_MIN_VOL_XMED = 1.5
SHORT_R1_USE_DOI_XMED_FILTER = False
SHORT_R1_MAX_DOI_XMED = 6.0
SHORT_R1_USE_DOI_CHANGE_FILTER = False
SHORT_R1_MIN_DOI_PCT = 0.0

# H3 — Confirmed R1 rejection. Experimental and OFF by default.
# Requires the reported high to have reached near/above the R1 upper boundary,
# then price to have pulled away from that high while still inside the R1 zone.
# The H/L fields are those known at the log timestamp, not future candle extremes.
SHORT_R1_CONFIRMED_MIN_ZONE_POSITION = 0.35
SHORT_R1_CONFIRMED_MAX_ZONE_POSITION = 0.98
# The cumulative hourly high must be close to the logged R1 upper boundary.
# -0.15% means it may be at most 0.15% below the boundary; +0.25% limits a small overshoot.
# The upper bound is critical: without it, a high far above R1 still counted as a touch.
SHORT_R1_CONFIRMED_MAX_HIGH_BELOW_ZONE_PCT = 0.15
SHORT_R1_CONFIRMED_MAX_HIGH_ABOVE_ZONE_PCT = 0.25
# Reject very late entries after price has already fallen too far from the local high.
SHORT_R1_CONFIRMED_MIN_PULLBACK_FROM_HIGH_PCT = 0.20
SHORT_R1_CONFIRMED_MAX_PULLBACK_FROM_HIGH_PCT = 0.65
SHORT_R1_CONFIRMED_MAX_RETURN_10M_PCT = -0.03
SHORT_R1_CONFIRMED_MAX_RETURN_30M_PCT = 0.00
SHORT_R1_CONFIRMED_USE_TAKER_FILTER = True
SHORT_R1_CONFIRMED_MAX_TAKER_BUY = 50.0
SHORT_R1_CONFIRMED_USE_ACTIVITY_FILTER = False
SHORT_R1_CONFIRMED_MIN_VOL_XMED = 1.5
SHORT_R1_CONFIRMED_USE_DOI_XMED_FILTER = False
SHORT_R1_CONFIRMED_MAX_DOI_XMED = 6.0

# H4 — Pump-then-reversal. Exploratory variant from the event study; OFF by default.
# A rally over the prior hour loses momentum, the current price moves away from the current-hour
# high, and activity is elevated. This is a candidate detector, not proof of a coming crash.
SHORT_PUMP_REVERSAL_MIN_RETURN_60M_PCT = 0.20
SHORT_PUMP_REVERSAL_MAX_RETURN_10M_PCT = -0.03
SHORT_PUMP_REVERSAL_MIN_PULLBACK_FROM_HOUR_HIGH_PCT = 0.05
SHORT_PUMP_REVERSAL_MAX_PULLBACK_FROM_HOUR_HIGH_PCT = 0.45
SHORT_PUMP_REVERSAL_MIN_VOL_XMED = 1.20
SHORT_PUMP_REVERSAL_USE_TAKER_FILTER = False
SHORT_PUMP_REVERSAL_MAX_TAKER_BUY = 55.0
SHORT_PUMP_REVERSAL_USE_DOI_FILTER = False
SHORT_PUMP_REVERSAL_MAX_DOI_PCT = 0.0

# H5 — OI-unwind + downside turn. Rare in the log-only event study; OFF pending OHLC validation.
# Required directional core: weak 10m/30m price action plus falling OI.
SHORT_OI_UNWIND_MAX_DOI_PCT = -0.10
SHORT_OI_UNWIND_MAX_RETURN_10M_PCT = -0.03
SHORT_OI_UNWIND_MAX_RETURN_30M_PCT = 0.00
SHORT_OI_UNWIND_USE_ACTIVITY_FILTER = True
SHORT_OI_UNWIND_MIN_VOL_XMED = 1.50
SHORT_OI_UNWIND_USE_DOI_XMED_FILTER = True
SHORT_OI_UNWIND_MIN_DOI_XMED = 1.00
SHORT_OI_UNWIND_USE_TAKER_FILTER = True
SHORT_OI_UNWIND_MAX_TAKER_BUY = 52.0

# H6 — S1 breakdown. Disabled by default; the first scan did not show encouraging follow-through.
SHORT_S1_USE_ZONE_POSITION_FILTER = False
SHORT_S1_MIN_ZONE_POSITION = -0.10
SHORT_S1_MAX_ZONE_POSITION = 0.50
SHORT_S1_MAX_RETURN_10M_PCT = -0.03
SHORT_S1_MAX_RETURN_30M_PCT = 0.00
SHORT_S1_USE_TAKER_FILTER = False
SHORT_S1_MAX_TAKER_BUY = 45.0
SHORT_S1_USE_ACTIVITY_FILTER = False
SHORT_S1_MIN_VOL_XMED = 1.5
SHORT_S1_USE_DOI_XMED_FILTER = False
SHORT_S1_MAX_DOI_XMED = 6.0

# Priority matters only when two enabled hypotheses fire on the same row.
SHORT_SIGNAL_PRIORITY = (
    "R1_CONFIRMED_REJECTION",
    "PUMP_THEN_REVERSAL",
    "OI_UNWIND_DOWNTURN",
    "R1_REJECTION",
    "TREND_CONTINUATION",
    "S1_BREAKDOWN",
)
