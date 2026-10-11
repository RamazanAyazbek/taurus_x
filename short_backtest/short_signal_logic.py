"""SHORT strategy logic, deliberately isolated from LONG signal rules."""
from __future__ import annotations

import re
import numpy as np
import pandas as pd

_ZONE_RE = re.compile(
    r"(?P<kind>[RS]1)\[\s*(?P<lo>[\d.]+)\s*k\s*[-–]\s*(?P<hi>[\d.]+)\s*k\s*\]",
    re.IGNORECASE,
)


def _parse_zone(value):
    text = str(value or "")
    match = _ZONE_RE.search(text)
    if not match:
        return ("NONE", np.nan, np.nan)
    low = float(match.group("lo")) * 1000.0
    high = float(match.group("hi")) * 1000.0
    if high <= low:
        return ("NONE", np.nan, np.nan)
    return (match.group("kind").upper(), low, high)


def prepare_short_features(df_logs: pd.DataFrame, cfg) -> pd.DataFrame:
    """Precompute lookback returns and zone position without using future rows.

    `dt` must be timezone-aware and sorted ascending. A return is None/NaN if the
    last observation at or before the target lookback is too stale.
    """
    if df_logs.empty:
        return df_logs.copy()

    df = df_logs.sort_values("dt").reset_index(drop=True).copy()
    t_ns = pd.to_datetime(df["dt"], utc=True).astype("int64").to_numpy()
    prices = df["price"].astype(float).to_numpy()

    windows = [
        (cfg.SHORT_LOOKBACK_10M, cfg.SHORT_MAX_GAP_10M, "short_return_10m_pct"),
        (cfg.SHORT_LOOKBACK_30M, cfg.SHORT_MAX_GAP_30M, "short_return_30m_pct"),
        (cfg.SHORT_LOOKBACK_60M, cfg.SHORT_MAX_GAP_60M, "short_return_60m_pct"),
        (cfg.SHORT_LOOKBACK_2H, cfg.SHORT_MAX_GAP_2H, "short_return_2h_pct"),
        (cfg.SHORT_LOOKBACK_4H, cfg.SHORT_MAX_GAP_4H, "short_return_4h_pct"),
    ]
    for minutes, max_gap, out_col in windows:
        target_ns = t_ns - int(minutes * 60 * 1_000_000_000)
        prev_idx = np.searchsorted(t_ns, target_ns, side="right") - 1
        returns = np.full(len(df), np.nan, dtype=float)
        valid = prev_idx >= 0
        safe_idx = np.maximum(prev_idx, 0)
        age_minutes = (t_ns - t_ns[safe_idx]) / 60_000_000_000
        valid &= age_minutes <= max_gap
        valid &= prices[safe_idx] > 0
        returns[valid] = (prices[valid] / prices[safe_idx[valid]] - 1.0) * 100.0
        df[out_col] = returns

    zones = [_parse_zone(value) for value in df.get("in_zone", pd.Series(["NONE"] * len(df)))]
    df["short_zone_type"] = [z[0] for z in zones]
    df["short_zone_low"] = [z[1] for z in zones]
    df["short_zone_high"] = [z[2] for z in zones]
    widths = df["short_zone_high"] - df["short_zone_low"]
    df["short_zone_position"] = (df["price"].astype(float) - df["short_zone_low"]) / widths
    reported_high = pd.to_numeric(df.get("hour_high", pd.Series(np.nan, index=df.index)), errors="coerce")
    price_values = pd.to_numeric(df["price"], errors="coerce")
    df["short_reported_high"] = reported_high
    # Difference between the observed intrahour high and the R1 upper boundary.
    # Positive means the high exceeded the zone top; negative means it stayed below it.
    df["short_high_delta_pct"] = (reported_high / df["short_zone_high"] - 1.0) * 100.0
    # Pullback measured from the current price to the known intrahour high.
    df["short_rejection_from_high_pct"] = (reported_high / price_values - 1.0) * 100.0
    return df


def _feature_value(curr, name):
    value = curr.get(name, np.nan)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _activity_ok(curr, cfg, prefix):
    if getattr(cfg, f"{prefix}_USE_ACTIVITY_FILTER"):
        vol_xmed = _feature_value(curr, "vol_xmed")
        if vol_xmed is None or vol_xmed < getattr(cfg, f"{prefix}_MIN_VOL_XMED"):
            return False
    if getattr(cfg, f"{prefix}_USE_DOI_XMED_FILTER"):
        doi_xmed = _feature_value(curr, "doi_xmed")
        if doi_xmed is None or doi_xmed > getattr(cfg, f"{prefix}_MAX_DOI_XMED"):
            return False
    return True


def evaluate_short_hypothesis(curr, cfg, hypothesis: str):
    """Evaluate one hypothesis at one row; ignores the master enable toggle.

    Returns a feature-rich metadata dict when conditions pass, otherwise None.
    `hypothesis` is one of TREND_CONTINUATION, R1_REJECTION,
    R1_CONFIRMED_REJECTION, PUMP_THEN_REVERSAL, OI_UNWIND_DOWNTURN or S1_BREAKDOWN.
    """
    name = hypothesis.upper()
    r10 = _feature_value(curr, "short_return_10m_pct")
    r30 = _feature_value(curr, "short_return_30m_pct")
    r60 = _feature_value(curr, "short_return_60m_pct")
    r2h = _feature_value(curr, "short_return_2h_pct")
    r4h = _feature_value(curr, "short_return_4h_pct")
    zone_type = str(curr.get("short_zone_type", "NONE")).upper()
    zone_pos = _feature_value(curr, "short_zone_position")
    zone_high = _feature_value(curr, "short_zone_high")
    price = _feature_value(curr, "price")
    reported_high = _feature_value(curr, "hour_high")
    pullback_from_high = _feature_value(curr, "short_rejection_from_high_pct")
    if pullback_from_high is None and reported_high is not None and price is not None and price > 0:
        pullback_from_high = (reported_high / price - 1.0) * 100.0
    high_delta_pct = _feature_value(curr, "short_high_delta_pct")
    if high_delta_pct is None and reported_high is not None and zone_high is not None and zone_high > 0:
        high_delta_pct = (reported_high / zone_high - 1.0) * 100.0
    taker_buy = _feature_value(curr, "taker_buy")

    if name == "TREND_CONTINUATION":
        if r4h is None or r2h is None or r10 is None:
            return None
        if not (
            r4h <= cfg.SHORT_TREND_4H_MAX_RETURN_PCT
            and r2h <= cfg.SHORT_TREND_2H_MAX_RETURN_PCT
            and r10 <= cfg.SHORT_TREND_10M_MAX_RETURN_PCT
        ):
            return None
        if cfg.SHORT_TREND_USE_TAKER_FILTER and (
            taker_buy is None or taker_buy > cfg.SHORT_TREND_MAX_TAKER_BUY
        ):
            return None
        if not _activity_ok(curr, cfg, "SHORT_TREND"):
            return None

    elif name == "R1_REJECTION":
        if zone_type != "R1" or zone_pos is None or r10 is None or r30 is None:
            return None
        if not (
            cfg.SHORT_R1_MIN_ZONE_POSITION <= zone_pos <= cfg.SHORT_R1_MAX_ZONE_POSITION
            and r10 <= cfg.SHORT_R1_MAX_RETURN_10M_PCT
            and r30 <= cfg.SHORT_R1_MAX_RETURN_30M_PCT
        ):
            return None
        if cfg.SHORT_R1_USE_TAKER_FILTER and (
            taker_buy is None or taker_buy > cfg.SHORT_R1_MAX_TAKER_BUY
        ):
            return None
        if not _activity_ok(curr, cfg, "SHORT_R1"):
            return None
        if cfg.SHORT_R1_USE_DOI_CHANGE_FILTER:
            doi_change = _feature_value(curr, "dOI")
            if doi_change is None or doi_change < cfg.SHORT_R1_MIN_DOI_PCT:
                return None

    elif name == "R1_CONFIRMED_REJECTION":
        if (
            zone_type != "R1" or zone_pos is None or zone_high is None
            or price is None or reported_high is None or high_delta_pct is None
            or r10 is None or r30 is None or pullback_from_high is None
        ):
            return None
        min_high_delta_pct = -float(cfg.SHORT_R1_CONFIRMED_MAX_HIGH_BELOW_ZONE_PCT)
        max_high_delta_pct = float(cfg.SHORT_R1_CONFIRMED_MAX_HIGH_ABOVE_ZONE_PCT)
        if not (
            cfg.SHORT_R1_CONFIRMED_MIN_ZONE_POSITION <= zone_pos <= cfg.SHORT_R1_CONFIRMED_MAX_ZONE_POSITION
            and min_high_delta_pct <= high_delta_pct <= max_high_delta_pct
            and cfg.SHORT_R1_CONFIRMED_MIN_PULLBACK_FROM_HIGH_PCT <= pullback_from_high <= cfg.SHORT_R1_CONFIRMED_MAX_PULLBACK_FROM_HIGH_PCT
            and r10 <= cfg.SHORT_R1_CONFIRMED_MAX_RETURN_10M_PCT
            and r30 <= cfg.SHORT_R1_CONFIRMED_MAX_RETURN_30M_PCT
        ):
            return None
        if cfg.SHORT_R1_CONFIRMED_USE_TAKER_FILTER and (
            taker_buy is None or taker_buy > cfg.SHORT_R1_CONFIRMED_MAX_TAKER_BUY
        ):
            return None
        if cfg.SHORT_R1_CONFIRMED_USE_ACTIVITY_FILTER:
            vol_xmed = _feature_value(curr, "vol_xmed")
            if vol_xmed is None or vol_xmed < cfg.SHORT_R1_CONFIRMED_MIN_VOL_XMED:
                return None
        if cfg.SHORT_R1_CONFIRMED_USE_DOI_XMED_FILTER:
            doi_xmed = _feature_value(curr, "doi_xmed")
            if doi_xmed is None or doi_xmed > cfg.SHORT_R1_CONFIRMED_MAX_DOI_XMED:
                return None

    elif name == "PUMP_THEN_REVERSAL":
        if r60 is None or r10 is None or pullback_from_high is None:
            return None
        if not (
            r60 >= cfg.SHORT_PUMP_REVERSAL_MIN_RETURN_60M_PCT
            and r10 <= cfg.SHORT_PUMP_REVERSAL_MAX_RETURN_10M_PCT
            and cfg.SHORT_PUMP_REVERSAL_MIN_PULLBACK_FROM_HOUR_HIGH_PCT <= pullback_from_high <= cfg.SHORT_PUMP_REVERSAL_MAX_PULLBACK_FROM_HOUR_HIGH_PCT
        ):
            return None
        vol_xmed = _feature_value(curr, "vol_xmed")
        if vol_xmed is None or vol_xmed < cfg.SHORT_PUMP_REVERSAL_MIN_VOL_XMED:
            return None
        if cfg.SHORT_PUMP_REVERSAL_USE_TAKER_FILTER and (
            taker_buy is None or taker_buy > cfg.SHORT_PUMP_REVERSAL_MAX_TAKER_BUY
        ):
            return None
        if cfg.SHORT_PUMP_REVERSAL_USE_DOI_FILTER:
            doi_change = _feature_value(curr, "dOI")
            if doi_change is None or doi_change > cfg.SHORT_PUMP_REVERSAL_MAX_DOI_PCT:
                return None

    elif name == "OI_UNWIND_DOWNTURN":
        # Empirical exploratory pattern: higher activity + negative OI change + weak price.
        # It had only nine observations on the non-overlapping 4h grid, so it is OFF by default.
        doi_change = _feature_value(curr, "dOI")
        doi_xmed = _feature_value(curr, "doi_xmed")
        vol_xmed = _feature_value(curr, "vol_xmed")
        if r10 is None or r30 is None or doi_change is None:
            return None
        if not (
            doi_change <= cfg.SHORT_OI_UNWIND_MAX_DOI_PCT
            and r10 <= cfg.SHORT_OI_UNWIND_MAX_RETURN_10M_PCT
            and r30 <= cfg.SHORT_OI_UNWIND_MAX_RETURN_30M_PCT
        ):
            return None
        if cfg.SHORT_OI_UNWIND_USE_ACTIVITY_FILTER and (
            vol_xmed is None or vol_xmed < cfg.SHORT_OI_UNWIND_MIN_VOL_XMED
        ):
            return None
        if cfg.SHORT_OI_UNWIND_USE_DOI_XMED_FILTER and (
            doi_xmed is None or doi_xmed < cfg.SHORT_OI_UNWIND_MIN_DOI_XMED
        ):
            return None
        if cfg.SHORT_OI_UNWIND_USE_TAKER_FILTER and (
            taker_buy is None or taker_buy > cfg.SHORT_OI_UNWIND_MAX_TAKER_BUY
        ):
            return None

    elif name == "S1_BREAKDOWN":
        if zone_type != "S1" or zone_pos is None or r10 is None or r30 is None:
            return None
        if cfg.SHORT_S1_USE_ZONE_POSITION_FILTER and not (
            zone_pos is not None
            and cfg.SHORT_S1_MIN_ZONE_POSITION <= zone_pos <= cfg.SHORT_S1_MAX_ZONE_POSITION
        ):
            return None
        if not (
            r10 <= cfg.SHORT_S1_MAX_RETURN_10M_PCT
            and r30 <= cfg.SHORT_S1_MAX_RETURN_30M_PCT
        ):
            return None
        if cfg.SHORT_S1_USE_TAKER_FILTER and (
            taker_buy is None or taker_buy > cfg.SHORT_S1_MAX_TAKER_BUY
        ):
            return None
        if not _activity_ok(curr, cfg, "SHORT_S1"):
            return None

    else:
        raise ValueError(f"Unknown SHORT hypothesis: {hypothesis}")

    return {
        "type": "SHORT",
        "short_hypothesis": name,
        "short_return_10m_pct": r10,
        "short_return_30m_pct": r30,
        "short_return_60m_pct": r60,
        "short_return_2h_pct": r2h,
        "short_return_4h_pct": r4h,
        "short_zone_position": zone_pos,
        "short_zone_type": zone_type,
        "short_zone_low": _feature_value(curr, "short_zone_low"),
        "short_zone_high": zone_high,
        "short_reported_high": reported_high,
        "short_high_delta_pct": high_delta_pct,
        "short_rejection_from_high_pct": pullback_from_high,
    }


def generate_short_signal(curr, cfg):
    """Return the first enabled SHORT hypothesis that passes, or None."""
    switches = {
        "TREND_CONTINUATION": cfg.ENABLE_SHORT_TREND_CONTINUATION,
        "R1_REJECTION": cfg.ENABLE_SHORT_R1_REJECTION,
        "R1_CONFIRMED_REJECTION": cfg.ENABLE_SHORT_R1_CONFIRMED_REJECTION,
        "PUMP_THEN_REVERSAL": cfg.ENABLE_SHORT_PUMP_REVERSAL,
        "OI_UNWIND_DOWNTURN": cfg.ENABLE_SHORT_OI_UNWIND_DOWNTURN,
        "S1_BREAKDOWN": cfg.ENABLE_SHORT_S1_BREAKDOWN,
    }
    for hypothesis in cfg.SHORT_SIGNAL_PRIORITY:
        if not switches.get(hypothesis, False):
            continue
        match = evaluate_short_hypothesis(curr, cfg, hypothesis)
        if match is not None:
            return match
    return None
