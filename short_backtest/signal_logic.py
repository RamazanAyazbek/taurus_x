from datetime import timedelta
import re


def get_previous_return(df_logs, current_dt, minutes):
    """Return of the latest log price versus a price at least `minutes` earlier.

    Kept for callers that pass a timestamp. Crucially, use the current timestamp's
    row rather than df_logs' final row (which could be future data in a backtest).
    """
    current_rows = df_logs[df_logs["dt"] <= current_dt]
    previous = df_logs[df_logs["dt"] <= current_dt - timedelta(minutes=minutes)].tail(1)
    if current_rows.empty or previous.empty:
        return None
    current = current_rows.iloc[-1]
    return (float(current["price"]) - float(previous.iloc[0]["price"])) / float(previous.iloc[0]["price"]) * 100


def get_previous_return_from_row(df_logs, curr, minutes):
    previous = df_logs[df_logs["dt"] <= curr["dt"] - timedelta(minutes=minutes)].tail(1)
    if previous.empty:
        return None
    return (float(curr["price"]) - float(previous.iloc[0]["price"])) / float(previous.iloc[0]["price"]) * 100


def get_recent_momentum_return(df_logs, curr, minutes, max_gap_minutes):
    """Return against the latest observation at least `minutes` old.

    The Taurus log's dPrice is measured from the start of the current hour, not
    necessarily from the previous log record, so it must not be used as 10m momentum.
    """
    target = curr["dt"] - timedelta(minutes=minutes)
    previous = df_logs[df_logs["dt"] <= target].tail(1)
    if previous.empty:
        return None
    gap = (curr["dt"] - previous.iloc[0]["dt"]).total_seconds() / 60
    if gap > max_gap_minutes:
        return None
    prev_price = float(previous.iloc[0]["price"])
    if prev_price <= 0:
        return None
    return (float(curr["price"]) - prev_price) / prev_price * 100


def calculate_market_context(df_logs, curr, config):
    context = {
        "previous_2h_return": None,
        "previous_4h_return": None,
        "previous_30m_return": None,
        "short_term_momentum_return": None,
    }
    if config.ENABLE_PREVIOUS_2H_4H:
        context["previous_2h_return"] = get_previous_return_from_row(df_logs, curr, 120)
        context["previous_4h_return"] = get_previous_return_from_row(df_logs, curr, 240)
    if config.ENABLE_PREVIOUS_30M:
        context["previous_30m_return"] = get_previous_return_from_row(df_logs, curr, 30)
    if getattr(config, "ENABLE_SHORT_TERM_MOMENTUM_FILTER", False):
        context["short_term_momentum_return"] = get_recent_momentum_return(
            df_logs, curr,
            config.MOMENTUM_LOOKBACK_MINUTES,
            config.MOMENTUM_MAX_LOOKBACK_GAP_MINUTES,
        )
    return context


def _parse_zone_bounds(zone_text):
    """Parse strings such as R1[86.8k-87.2k] into numeric bounds."""
    if not isinstance(zone_text, str):
        return None
    match = re.search(r"R1\[\s*([\d.]+)\s*k\s*-\s*([\d.]+)\s*k\s*\]", zone_text, re.I)
    if not match:
        return None
    return float(match.group(1)) * 1000, float(match.group(2)) * 1000


def passes_r1_breakout_retest(df_logs, curr, config):
    """Non-R1 entries pass. R1 entries need prior move above R1 and a retest.

    Retest must be near the upper boundary (configured tolerance). The prior window
    must contain a move from at/below the upper boundary to above it, followed by
    the current price returning near that boundary. Missing/ambiguous zone data fails
    closed for an R1-labelled entry.
    """
    zone = str(curr.get("in_zone", "NONE"))
    if not zone.upper().startswith("R1["):
        return True
    bounds = _parse_zone_bounds(zone)
    if bounds is None:
        return False
    _, upper = bounds
    price = float(curr["price"])
    tolerance = config.R1_RETEST_TOLERANCE_PCT / 100
    near_upper = upper * (1 - tolerance) <= price <= upper * (1 + tolerance)
    if not near_upper:
        return False

    start_dt = curr["dt"] - timedelta(minutes=config.R1_RETEST_LOOKBACK_MINUTES)
    history = df_logs[(df_logs["dt"] >= start_dt) & (df_logs["dt"] < curr["dt"])].sort_values("dt")
    was_at_or_below = False
    breakout_seen = False
    for _, row in history.iterrows():
        row_price = float(row["price"])
        if row_price <= upper:
            was_at_or_below = True
        elif was_at_or_below and row_price > upper:
            breakout_seen = True
    return breakout_seen


def basic_filters(curr, config):
    return (
        curr["vol_xmed"] >= config.VOLUME_XMED_MIN
        and curr["volume"] >= config.VOLUME_MIN
        and curr["doi_xmed"] <= config.OI_XMED_MAX
    )


def current_market_state(curr, config):
    return (
        basic_filters(curr, config)
        and curr["dOI"] >= config.CURRENT_DOI_MIN
        and curr["vol_xmed"] >= config.CURRENT_VOLUME_XMED_MIN
    )


def generate_signal(curr, context, current_state, config, df_logs=None):
    if not current_state:
        return None

    p4 = context.get("previous_4h_return")
    p2 = context.get("previous_2h_return")
    p30 = context.get("previous_30m_return")

    if config.ENABLE_PREVIOUS_2H_4H and (p4 is None or p2 is None):
        return None
    if config.ENABLE_PREVIOUS_30M and p30 is None:
        return None

    momentum = context.get("short_term_momentum_return")
    common_history_ready = (
        (not config.ENABLE_PREVIOUS_2H_4H or (p4 is not None and p2 is not None))
        and (not config.ENABLE_PREVIOUS_30M or p30 is not None)
    )
    if not common_history_ready:
        return None

    # LONG setup: activity + non-negative 2h trend, no overextension, buyer imbalance cap.
    long_ok = True
    if config.ENABLE_PREVIOUS_2H_4H:
        long_ok = long_ok and p4 <= config.PREVIOUS_4H_RETURN_MAX and p2 >= config.PREVIOUS_2H_RETURN_MIN
        if getattr(config, "ENABLE_4H_BULL_REGIME_FILTER", False):
            long_ok = long_ok and p4 >= config.PREVIOUS_4H_RETURN_MIN
    if config.ENABLE_PREVIOUS_30M:
        long_ok = long_ok and p30 <= config.PREVIOUS_30M_RETURN_MAX
    long_ok = long_ok and curr["taker_buy"] <= config.TAKER_BUY_MAX
    if getattr(config, "ENABLE_SHORT_TERM_MOMENTUM_FILTER", False):
        long_ok = long_ok and momentum is not None and momentum > config.MOMENTUM_MIN_RETURN_PCT
    if long_ok and getattr(config, "ENABLE_R1_BREAKOUT_RETEST_FILTER", False):
        long_ok = df_logs is not None and passes_r1_breakout_retest(df_logs, curr, config)
    if long_ok:
        return "LONG"

    # This module owns LONG signals only. SHORT hypotheses are intentionally isolated
    # in short_signal_logic.py with their own short_config.py thresholds.
    return None
