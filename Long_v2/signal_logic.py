"""LONG signal logic with causal, precomputed historical features."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd


def _to_float_or_none(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def get_previous_return(df_logs, current_dt, minutes):
    """Return current-price change vs the last observation <= current_dt - minutes.

    Kept for compatibility with older scripts. It intentionally does not use the
    final row of the dataframe, which would introduce look-ahead leakage.
    """
    current = df_logs[df_logs["dt"] <= current_dt].tail(1)
    previous = df_logs[df_logs["dt"] <= current_dt - timedelta(minutes=minutes)].tail(1)
    if current.empty or previous.empty:
        return None
    prev_price = _to_float_or_none(previous.iloc[0]["price"])
    current_price = _to_float_or_none(current.iloc[0]["price"])
    if prev_price is None or current_price is None or prev_price <= 0:
        return None
    return (current_price / prev_price - 1.0) * 100.0


def get_previous_return_from_row(df_logs, curr, minutes):
    """Fallback calculation for an unprepared row."""
    previous = df_logs[df_logs["dt"] <= curr["dt"] - timedelta(minutes=minutes)].tail(1)
    if previous.empty:
        return None
    previous_price = _to_float_or_none(previous.iloc[0]["price"])
    current_price = _to_float_or_none(curr["price"])
    if previous_price is None or current_price is None or previous_price <= 0:
        return None
    return (current_price / previous_price - 1.0) * 100.0


def _add_lookback_return(df: pd.DataFrame, minutes: int, max_age_minutes: int, column: str) -> None:
    """Vectorized point-in-time return; all observations are at/before each target."""
    times_ns = pd.DatetimeIndex(df["dt"]).asi8
    prices = df["price"].astype(float).to_numpy()
    target_ns = times_ns - int(minutes * 60 * 1_000_000_000)
    previous_idx = np.searchsorted(times_ns, target_ns, side="right") - 1
    values = np.full(len(df), np.nan, dtype=float)
    valid = previous_idx >= 0
    safe_idx = np.maximum(previous_idx, 0)
    # The observation's total age relative to the current row must not be stale.
    age_minutes = (times_ns - times_ns[safe_idx]) / 60_000_000_000
    valid &= age_minutes <= max_age_minutes
    valid &= prices[safe_idx] > 0
    valid &= prices > 0
    values[valid] = (prices[valid] / prices[safe_idx[valid]] - 1.0) * 100.0
    df[column] = values


def prepare_long_features(df_logs: pd.DataFrame, config) -> pd.DataFrame:
    """Precompute historical returns and the long-term trend filter once.

    Complexity is approximately O(n log n), rather than repeatedly scanning all
    rows for every candidate signal. Rolling trend values use past observations only.
    """
    if df_logs.empty:
        return df_logs.copy()

    df = df_logs.copy()
    df["dt"] = pd.to_datetime(df["dt"], utc=True, errors="coerce")
    df = (
        df.dropna(subset=["dt", "price"])
        .sort_values("dt")
        .drop_duplicates(subset="dt", keep="last")
        .reset_index(drop=True)
    )

    windows = [
        (30, getattr(config, "LONG_MAX_AGE_30M", 45), "previous_30m_return"),
        (120, getattr(config, "LONG_MAX_AGE_2H", 150), "previous_2h_return"),
        (240, getattr(config, "LONG_MAX_AGE_4H", 270), "previous_4h_return"),
        (720, getattr(config, "LONG_MAX_AGE_12H", 750), "previous_12h_return"),
        (2880, getattr(config, "LONG_MAX_AGE_48H", 2940), "previous_48h_return"),
    ]
    for minutes, max_age, column in windows:
        _add_lookback_return(df, minutes, max_age, column)

    # Time-based rolling average avoids assuming exactly 10 minutes between rows.
    # It requires >= 2/3 of the expected 10-minute observations within the window;
    # gaps in the log therefore result in a missing trend, not a guessed trend.
    sma_hours = max(1, int(getattr(config, "LONG_TREND_SMA_HOURS", 12)))
    slope_hours = max(1, int(getattr(config, "LONG_TREND_SLOPE_LOOKBACK_HOURS", 2)))
    expected_samples = sma_hours * 6
    min_samples = max(18, int(expected_samples * 2 / 3))
    price_series = pd.Series(
        df["price"].astype(float).to_numpy(),
        index=pd.DatetimeIndex(df["dt"]),
    )
    sma = price_series.rolling(f"{sma_hours}h", min_periods=min_samples).mean()
    sma_values = sma.to_numpy(dtype=float)

    times_ns = pd.DatetimeIndex(df["dt"]).asi8
    target_ns = times_ns - int(slope_hours * 60 * 60 * 1_000_000_000)
    previous_idx = np.searchsorted(times_ns, target_ns, side="right") - 1
    safe_idx = np.maximum(previous_idx, 0)
    target_age_minutes = (target_ns - times_ns[safe_idx]) / 60_000_000_000
    max_stale = float(getattr(config, "LONG_TREND_MAX_STALE_MINUTES", 20))

    slope = np.full(len(df), np.nan, dtype=float)
    current_sma = sma_values
    prior_sma = sma_values[safe_idx]
    valid = previous_idx >= 0
    valid &= target_age_minutes <= max_stale
    valid &= np.isfinite(current_sma) & np.isfinite(prior_sma)
    valid &= current_sma > 0
    valid &= prior_sma > 0
    slope[valid] = (current_sma[valid] / prior_sma[valid] - 1.0) * 100.0

    df["long_sma_12h_slope_2h_pct"] = slope
    df["long_price_vs_sma_12h_pct"] = np.where(
        np.isfinite(current_sma) & (current_sma > 0),
        (df["price"].astype(float).to_numpy() / current_sma - 1.0) * 100.0,
        np.nan,
    )
    return df


def calculate_market_context(df_logs, curr, config):
    """Read precomputed context; fall back to direct calculation for old callers."""
    values = {
        "previous_2h_return": _to_float_or_none(curr.get("previous_2h_return")),
        "previous_4h_return": _to_float_or_none(curr.get("previous_4h_return")),
        "previous_30m_return": _to_float_or_none(curr.get("previous_30m_return")),
        "previous_12h_return": _to_float_or_none(curr.get("previous_12h_return")),
        "previous_48h_return": _to_float_or_none(curr.get("previous_48h_return")),
        "long_sma_12h_slope_2h_pct": _to_float_or_none(curr.get("long_sma_12h_slope_2h_pct")),
        "long_price_vs_sma_12h_pct": _to_float_or_none(curr.get("long_price_vs_sma_12h_pct")),
    }
    if "previous_2h_return" not in curr.index:
        values["previous_2h_return"] = get_previous_return_from_row(df_logs, curr, 120)
    if "previous_4h_return" not in curr.index:
        values["previous_4h_return"] = get_previous_return_from_row(df_logs, curr, 240)
    if "previous_30m_return" not in curr.index:
        values["previous_30m_return"] = get_previous_return_from_row(df_logs, curr, 30)
    return values


def basic_filters(curr, config):
    return (
        float(curr.get("vol_xmed", 0) or 0) >= config.VOLUME_XMED_MIN
        and float(curr.get("volume", 0) or 0) >= config.VOLUME_MIN
        and float(curr.get("doi_xmed", 0) or 0) <= config.OI_XMED_MAX
    )


def current_market_state(curr, config):
    return (
        basic_filters(curr, config)
        and float(curr.get("dOI", -np.inf) or 0) >= config.CURRENT_DOI_MIN
        and float(curr.get("vol_xmed", 0) or 0) >= config.CURRENT_VOLUME_XMED_MIN
    )


def generate_signal(curr, context, current_state, config):
    """Return LONG only when short-term momentum and broad trend conditions agree."""
    if not current_state:
        return None

    if config.ENABLE_PREVIOUS_2H_4H:
        previous_4h = context.get("previous_4h_return")
        previous_2h = context.get("previous_2h_return")
        if previous_4h is None or previous_2h is None:
            return None
        if previous_4h > config.PREVIOUS_4H_RETURN_MAX:
            return None
        if previous_4h < getattr(config, "PREVIOUS_4H_RETURN_MIN", -np.inf):
            return None
        if previous_2h < config.PREVIOUS_2H_RETURN_MIN:
            return None

    if config.ENABLE_PREVIOUS_30M:
        previous_30m = context.get("previous_30m_return")
        if previous_30m is None or previous_30m > config.PREVIOUS_30M_RETURN_MAX:
            return None

    if float(curr.get("taker_buy", np.inf)) > config.TAKER_BUY_MAX:
        return None

    if getattr(config, "ENABLE_LONG_TREND_FILTER", False):
        trend_slope = context.get("long_sma_12h_slope_2h_pct")
        if trend_slope is None:
            return None  # missing/stale trend history must not be treated as bullish
        min_slope = float(getattr(config, "LONG_TREND_MIN_SMA_SLOPE_PCT", 0.0))
        if trend_slope <= min_slope:
            return None

    if getattr(config, "ENABLE_LONG_R1_REJECTION", False):
        zone = str(curr.get("in_zone", "NONE") or "NONE").strip().upper()
        if zone.startswith("R1"):
            return None

    return "LONG"
