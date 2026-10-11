"""Research possible SHORT precursors from Taurus snapshots.

This is a LOG-ONLY EVENT STUDY, not a Binance OHLC backtest and not a live signal.
It reports fixed-horizon close returns and close-observed excursions. Intraminute
high/low, order of TP/SL touches, funding, liquidations and order-book depth are not
recoverable from these log snapshots.

Run from the project root:
    py .\research_short_precursors.py
    py .\research_short_precursors.py --log data\taurus_x_container.log

Writes three CSVs in --output-dir (default: data):
    short_precursor_pattern_summary.csv
    short_precursor_feature_rows.csv
    short_precursor_drop_events.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Callable

import numpy as np
import pandas as pd

import config
import short_config
from log_parser import parse_taurus_log
from short_signal_logic import prepare_short_features

HORIZON_MINUTES = 240
MAX_FORWARD_SNAPSHOT_LAG_MINUTES = 30
EVENT_DROP_THRESHOLDS_PCT = (-0.7, -1.5)
TP_PCT = 1.5
SL_PCT = 0.7


def _time_ns(df: pd.DataFrame) -> np.ndarray:
    return pd.to_datetime(df["dt"], utc=True).astype("int64").to_numpy()


def _lookback_delta(values: np.ndarray, times_ns: np.ndarray, minutes: int,
                    max_staleness_minutes: int) -> np.ndarray:
    target = times_ns - int(minutes * 60 * 1_000_000_000)
    idx = np.searchsorted(times_ns, target, side="right") - 1
    out = np.full(len(values), np.nan, dtype=float)
    valid = idx >= 0
    safe_idx = np.maximum(idx, 0)
    age = (times_ns - times_ns[safe_idx]) / 60_000_000_000
    valid &= age <= max_staleness_minutes
    values = np.asarray(values, dtype=float)
    valid &= np.isfinite(values) & np.isfinite(values[safe_idx])
    out[valid] = values[valid] - values[safe_idx[valid]]
    return out


def _lookback_return_pct(prices: np.ndarray, times_ns: np.ndarray, minutes: int,
                         max_staleness_minutes: int) -> np.ndarray:
    target = times_ns - int(minutes * 60 * 1_000_000_000)
    idx = np.searchsorted(times_ns, target, side="right") - 1
    out = np.full(len(prices), np.nan, dtype=float)
    valid = idx >= 0
    safe_idx = np.maximum(idx, 0)
    age = (times_ns - times_ns[safe_idx]) / 60_000_000_000
    valid &= age <= max_staleness_minutes
    valid &= np.isfinite(prices) & (prices > 0) & np.isfinite(prices[safe_idx]) & (prices[safe_idx] > 0)
    out[valid] = (prices[valid] / prices[safe_idx[valid]] - 1.0) * 100.0
    return out


def _add_forward_targets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().sort_values("dt").reset_index(drop=True)
    times_ns = _time_ns(out)
    prices = pd.to_numeric(out["price"], errors="coerce").to_numpy(dtype=float)
    horizon_ns = int(HORIZON_MINUTES * 60 * 1_000_000_000)
    target_ns = times_ns + horizon_ns
    idx = np.searchsorted(times_ns, target_ns, side="left")

    forward_return = np.full(len(out), np.nan, dtype=float)
    forward_age = np.full(len(out), np.nan, dtype=float)
    valid = idx < len(out)
    safe_idx = np.minimum(idx, len(out) - 1)
    forward_age[valid] = (times_ns[safe_idx[valid]] - times_ns[valid]) / 60_000_000_000
    valid &= forward_age <= HORIZON_MINUTES + MAX_FORWARD_SNAPSHOT_LAG_MINUTES
    valid &= prices > 0
    valid &= prices[safe_idx] > 0
    forward_return[valid] = (prices[safe_idx[valid]] / prices[valid] - 1.0) * 100.0
    out["forward_4h_close_return_pct"] = forward_return
    out["forward_4h_observation_age_min"] = forward_age

    # Use the subsequent observed CLOSES only. This is not true OHLC MFE/MAE.
    short_mfe = np.full(len(out), np.nan, dtype=float)
    short_mae = np.full(len(out), np.nan, dtype=float)
    opportunity = np.full(len(out), np.nan, dtype=object)
    for i, t in enumerate(times_ns):
        end_idx = np.searchsorted(times_ns, t + horizon_ns, side="right")
        if end_idx <= i + 1:
            continue
        last_time = times_ns[end_idx - 1]
        coverage = (last_time - t) / 60_000_000_000
        if coverage < HORIZON_MINUTES - MAX_FORWARD_SNAPSHOT_LAG_MINUTES:
            continue
        future = prices[i + 1:end_idx]
        future = future[np.isfinite(future) & (future > 0)]
        if not len(future) or not np.isfinite(prices[i]) or prices[i] <= 0:
            continue
        # MFE/MAE are excursions, so they cannot be negative when price never moved that way.
        short_mfe[i] = max(0.0, (prices[i] - np.min(future)) / prices[i] * 100.0)
        short_mae[i] = max(0.0, (np.max(future) - prices[i]) / prices[i] * 100.0)
        opportunity[i] = bool(short_mfe[i] >= TP_PCT and short_mae[i] < SL_PCT)

    out["close_only_short_mfe_4h_pct"] = short_mfe
    out["close_only_short_mae_4h_pct"] = short_mae
    out["close_only_tp15_mae_below_sl07_4h"] = opportunity

    for threshold in EVENT_DROP_THRESHOLDS_PCT:
        label = f"forward_4h_drop_at_least_{abs(threshold):.1f}pct"
        out[label] = out["forward_4h_close_return_pct"] <= threshold
    return out


def _sample_grid(df: pd.DataFrame, interval_minutes: int, max_lag_minutes: int = 20) -> pd.DataFrame:
    """Choose one observed row per anchored time-grid point, without using future price outcomes."""
    if df.empty:
        return df.copy()
    times = _time_ns(df)
    step_ns = int(interval_minutes * 60 * 1_000_000_000)
    target = int(times[0])
    last = int(times[-1]) - HORIZON_MINUTES * 60 * 1_000_000_000
    selected = []
    while target <= last:
        idx = int(np.searchsorted(times, target, side="left"))
        if idx < len(times):
            delay_min = (times[idx] - target) / 60_000_000_000
            if 0 <= delay_min <= max_lag_minutes and (not selected or idx > selected[-1]):
                selected.append(idx)
        target += step_ns
    sampled = df.iloc[selected].copy().reset_index(drop=True)
    sampled["sampling_interval_min"] = interval_minutes
    return sampled


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (np.nan, np.nan)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n))) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _pattern_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    ret10 = pd.to_numeric(df.get("short_return_10m_pct"), errors="coerce")
    ret30 = pd.to_numeric(df.get("short_return_30m_pct"), errors="coerce")
    ret60 = pd.to_numeric(df.get("short_return_60m_pct"), errors="coerce")
    ret120 = pd.to_numeric(df.get("short_return_2h_pct"), errors="coerce")
    ret240 = pd.to_numeric(df.get("short_return_4h_pct"), errors="coerce")
    zone_pos = pd.to_numeric(df.get("short_zone_position"), errors="coerce")
    zone_type = df.get("short_zone_type", pd.Series("NONE", index=df.index)).astype(str)
    high_delta = pd.to_numeric(df.get("short_high_delta_pct"), errors="coerce")
    pullback = pd.to_numeric(df.get("short_rejection_from_high_pct"), errors="coerce")
    dist_high = pd.to_numeric(df.get("distance_from_hour_high_pct"), errors="coerce")
    hour_range = pd.to_numeric(df.get("hour_range_pct"), errors="coerce")
    vol = pd.to_numeric(df.get("vol_xmed"), errors="coerce")
    doi_ratio = pd.to_numeric(df.get("doi_xmed"), errors="coerce")
    doi = pd.to_numeric(df.get("dOI"), errors="coerce")
    taker = pd.to_numeric(df.get("taker_buy"), errors="coerce")
    taker_change_30 = pd.to_numeric(df.get("taker_buy_change_30m"), errors="coerce")
    dprice = pd.to_numeric(df.get("dPrice"), errors="coerce")

    return {
        "ALL_ROWS_BASELINE": pd.Series(True, index=df.index),
        "HIGH_VOLUME vol_xmed>=1.5": vol >= 1.5,
        "WIDE_CURRENT_HOUR_RANGE>=0.4pct": hour_range >= 0.4,
        "HIGH_VOLUME_AND_WIDE_RANGE": (vol >= 1.5) & (hour_range >= 0.4),
        "OI_ACTIVITY_RATIO>=1.0": doi_ratio >= 1.0,
        "OI_CHANGE<=-0.15pct": doi <= -0.15,
        "TAKER_BUY>=58pct": taker >= 58.0,
        "MOMENTUM_DOWN_30m<=-0.2pct": ret30 <= -0.2,
        "TREND_DOWN_2h<=-0.4pct": ret120 <= -0.4,
        "PUMP_THEN_10m_REVERSAL": (ret60 >= 0.2) & (ret10 <= -0.03) & dist_high.between(0.05, 0.45) & (vol >= 1.2),
        "R1_STRICT_CONFIRMED_REJECTION": (
            zone_type.eq("R1") & zone_pos.between(0.35, 0.98)
            & high_delta.between(-0.15, 0.25) & pullback.between(0.20, 0.65)
            & (ret10 <= -0.03) & (ret30 <= 0.0) & (taker <= 50.0)
        ),
        "VOL_RANGE_DOWNTURN": (vol >= 1.5) & (hour_range >= 0.4) & (ret10 <= -0.03) & (ret30 <= 0) & (taker <= 52),
        "OI_UNWIND_DOWNTURN": (vol >= 1.5) & (doi <= -0.10) & (doi_ratio >= 1.0) & (ret10 <= -0.03) & (ret30 <= 0) & (taker <= 52),
        "OI_RISING_PRICE_STALL": (doi >= 0.10) & (dprice <= 0.10) & (taker_change_30 <= -5.0),
    }


def _summarize_patterns(samples: pd.DataFrame, resolution: str) -> pd.DataFrame:
    valid = samples["forward_4h_close_return_pct"].notna()
    data = samples.loc[valid].copy()
    if data.empty:
        return pd.DataFrame()
    target07 = data["forward_4h_close_return_pct"] <= -0.7
    target15 = data["forward_4h_close_return_pct"] <= -1.5
    opportunity_valid = data["close_only_tp15_mae_below_sl07_4h"].notna()
    target_opportunity = data["close_only_tp15_mae_below_sl07_4h"].map(lambda value: bool(value) if pd.notna(value) else False).astype(bool)
    base07 = float(target07.mean())
    base15 = float(target15.mean())
    baseopp = float(target_opportunity[opportunity_valid].mean()) if opportunity_valid.any() else np.nan
    records = []
    for name, raw_mask in _pattern_masks(data).items():
        mask = raw_mask.fillna(False).astype(bool)
        n = int(mask.sum())
        if n == 0:
            records.append({"sample_resolution": resolution, "pattern": name, "n": 0})
            continue
        yy07 = target07[mask]
        yy15 = target15[mask]
        opportunity_mask = mask & opportunity_valid
        yyopp = target_opportunity[opportunity_mask]
        n_opp = int(opportunity_mask.sum())
        lo07, hi07 = _wilson_interval(int(yy07.sum()), n)
        lo15, hi15 = _wilson_interval(int(yy15.sum()), n)
        loopp, hiopp = _wilson_interval(int(yyopp.sum()), n_opp)
        records.append({
            "sample_resolution": resolution,
            "pattern": name,
            "n": n,
            "drop_0.7pct_in_4h_n": int(yy07.sum()),
            "drop_0.7pct_in_4h_rate_pct": 100 * float(yy07.mean()),
            "drop_0.7pct_rate_ci95_low_pct": 100 * lo07,
            "drop_0.7pct_rate_ci95_high_pct": 100 * hi07,
            "lift_vs_base_drop_0.7pct": float(yy07.mean() / base07) if base07 > 0 else np.nan,
            "drop_1.5pct_in_4h_n": int(yy15.sum()),
            "drop_1.5pct_in_4h_rate_pct": 100 * float(yy15.mean()),
            "drop_1.5pct_rate_ci95_low_pct": 100 * lo15,
            "drop_1.5pct_rate_ci95_high_pct": 100 * hi15,
            "lift_vs_base_drop_1.5pct": float(yy15.mean() / base15) if base15 > 0 else np.nan,
            "close_only_opportunity_sample_n": n_opp,
            "close_only_short_opportunity_n": int(yyopp.sum()),
            "close_only_short_opportunity_rate_pct": 100 * float(yyopp.mean()) if n_opp else np.nan,
            "close_only_opportunity_ci95_low_pct": 100 * loopp,
            "close_only_opportunity_ci95_high_pct": 100 * hiopp,
            "lift_vs_base_close_only_opportunity": float(yyopp.mean() / baseopp) if n_opp and baseopp > 0 else np.nan,
            "mean_forward_4h_short_return_pct": float(-data.loc[mask, "forward_4h_close_return_pct"].mean()),
            "base_drop_0.7pct_rate_pct": 100 * base07,
            "base_drop_1.5pct_rate_pct": 100 * base15,
            "base_close_only_opportunity_rate_pct": 100 * baseopp,
            "note": "Descriptive only; hourly horizons overlap. 4h grid reduces overlap but is small-N." if resolution == "hourly_grid_overlapping" else "Lower overlap; event counts are small; not a validated trading edge.",
        })
    return pd.DataFrame(records)


def _select_drop_events(hourly: pd.DataFrame, threshold_pct: float = -1.5,
                        cooldown_minutes: int = 240) -> pd.DataFrame:
    candidates = hourly.loc[hourly["forward_4h_close_return_pct"] <= threshold_pct].sort_values("dt")
    keep = []
    last_dt = None
    for idx, row in candidates.iterrows():
        if last_dt is None or (row["dt"] - last_dt).total_seconds() / 60 >= cooldown_minutes:
            keep.append(idx)
            last_dt = row["dt"]
    out = candidates.loc[keep].copy()
    out["event_definition"] = f"next observed 4h close return <= {threshold_pct:.1f}%; one candidate per {cooldown_minutes}m cooldown"
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default=config.LOG_FILE, help="Taurus log path; defaults to config.LOG_FILE")
    parser.add_argument("--output-dir", default="data", help="output directory; defaults to data")
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    if not log_path.exists():
        raise SystemExit(f"Log file not found: {log_path}")
    df = parse_taurus_log(str(log_path))
    if df.empty:
        raise SystemExit(f"No Taurus price rows parsed from {log_path}")
    df = prepare_short_features(df, short_config)
    _times_ns = _time_ns(df)
    _prices = pd.to_numeric(df["price"], errors="coerce").to_numpy(dtype=float)
    df["short_return_60m_pct"] = _lookback_return_pct(_prices, _times_ns, 60, 80)

    df["distance_from_hour_high_pct"] = (pd.to_numeric(df["hour_high"], errors="coerce") / df["price"] - 1) * 100
    df["hour_range_pct"] = (pd.to_numeric(df["hour_high"], errors="coerce") - pd.to_numeric(df["hour_low"], errors="coerce")) / df["price"] * 100
    df["short_high_delta_pct"] = (pd.to_numeric(df["hour_high"], errors="coerce") / pd.to_numeric(df["short_zone_high"], errors="coerce") - 1) * 100
    for col in ("dOI", "taker_buy", "vol_xmed"):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
            df[f"{col}_change_30m"] = _lookback_delta(vals, _time_ns(df), 30, 45)
    df = _add_forward_targets(df)

    # The hourly sample gives a more stable descriptive picture but overlapping 4h targets.
    hourly = df.copy()
    hourly["_hour_bucket"] = pd.to_datetime(hourly["dt"], utc=True).dt.floor("h")
    hourly = hourly.sort_values("dt").groupby("_hour_bucket", sort=True).tail(1).sort_values("dt").reset_index(drop=True)
    hourly = hourly.loc[hourly["forward_4h_close_return_pct"].notna()].copy().reset_index(drop=True)
    grid4h = _sample_grid(df, interval_minutes=240)
    grid4h = grid4h.loc[grid4h["forward_4h_close_return_pct"].notna()].copy().reset_index(drop=True)

    summary = pd.concat([
        _summarize_patterns(hourly, "hourly_grid_overlapping"),
        _summarize_patterns(grid4h, "nonoverlap_4h_grid"),
    ], ignore_index=True)
    event_rows = _select_drop_events(hourly, threshold_pct=-1.5, cooldown_minutes=240)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "short_precursor_pattern_summary.csv"
    rows_path = output_dir / "short_precursor_feature_rows.csv"
    events_path = output_dir / "short_precursor_drop_events.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    feature_cols = [
        "timestamp", "price", "dPrice", "dOI", "doi_xmed", "vol_xmed", "taker_buy", "in_zone",
        "short_return_10m_pct", "short_return_30m_pct", "short_return_2h_pct", "short_return_4h_pct",
        "short_zone_type", "short_zone_position", "short_zone_low", "short_zone_high",
        "short_high_delta_pct", "short_rejection_from_high_pct", "distance_from_hour_high_pct", "hour_range_pct",
        "dOI_change_30m", "taker_buy_change_30m", "vol_xmed_change_30m",
        "forward_4h_close_return_pct", "forward_4h_observation_age_min",
        "close_only_short_mfe_4h_pct", "close_only_short_mae_4h_pct", "close_only_tp15_mae_below_sl07_4h",
        "forward_4h_drop_at_least_0.7pct", "forward_4h_drop_at_least_1.5pct",
    ]
    present = [c for c in feature_cols if c in df.columns]
    df[present].to_csv(rows_path, index=False, encoding="utf-8-sig")
    evcols = [c for c in present if c not in {"forward_4h_drop_at_least_0.7pct"}]
    event_rows[[c for c in evcols if c in event_rows.columns] + ["event_definition"]].to_csv(events_path, index=False, encoding="utf-8-sig")

    first_price, last_price = float(df.iloc[0]["price"]), float(df.iloc[-1]["price"])
    total_return = (last_price / first_price - 1) * 100
    valid_hourly = hourly["forward_4h_close_return_pct"].notna()
    h = hourly.loc[valid_hourly]
    drop07 = int((h["forward_4h_close_return_pct"] <= -0.7).sum())
    drop15 = int((h["forward_4h_close_return_pct"] <= -1.5).sum())
    opp = int(h["close_only_tp15_mae_below_sl07_4h"].sum())

    print("\nTAURUS PRE-DROP RESEARCH | log-close event study; NOT an OHLC backtest")
    print(f"Rows: {len(df):,} | Period (Almaty): {df['dt_local'].min()} -> {df['dt_local'].max()}")
    print(f"First-to-last BTC return: {total_return:+.2f}% | hourly samples: {len(h):,} | non-overlap 4h samples: {len(grid4h):,}")
    print(f"Hourly sample base rates (overlapping 4h outcomes): drop >=0.7%: {drop07}/{len(h)} ({drop07/max(1,len(h))*100:.1f}%), drop >=1.5%: {drop15}/{len(h)} ({drop15/max(1,len(h))*100:.1f}%), close-only TP/MAE proxy: {opp}/{len(h)} ({opp/max(1,len(h))*100:.1f}%)")
    print("\nNon-overlapping 4h-grid diagnostic (small sample; main comparison):")
    main_summary = summary.loc[summary["sample_resolution"].eq("nonoverlap_4h_grid")].copy()
    core = main_summary.loc[main_summary["pattern"].isin([
        "ALL_ROWS_BASELINE", "HIGH_VOLUME vol_xmed>=1.5", "WIDE_CURRENT_HOUR_RANGE>=0.4pct",
        "HIGH_VOLUME_AND_WIDE_RANGE", "OI_ACTIVITY_RATIO>=1.0", "OI_CHANGE<=-0.15pct",
        "TAKER_BUY>=58pct", "MOMENTUM_DOWN_30m<=-0.2pct", "TREND_DOWN_2h<=-0.4pct",
        "PUMP_THEN_10m_REVERSAL", "R1_STRICT_CONFIRMED_REJECTION", "OI_UNWIND_DOWNTURN",
        "VOL_RANGE_DOWNTURN",
    ])]
    if not core.empty:
        cols = ["pattern", "n", "drop_0.7pct_in_4h_n", "drop_0.7pct_in_4h_rate_pct", "drop_1.5pct_in_4h_n", "drop_1.5pct_in_4h_rate_pct", "close_only_short_opportunity_n", "close_only_short_opportunity_rate_pct"]
        print(core[cols].to_string(index=False, formatters={
            "drop_0.7pct_in_4h_rate_pct": lambda x: f"{x:.1f}%",
            "drop_1.5pct_in_4h_rate_pct": lambda x: f"{x:.1f}%",
            "close_only_short_opportunity_rate_pct": lambda x: f"{x:.1f}%",
        }))
    print(f"\nSevere-drop candidates after 240m cooldown: {len(event_rows)} (observed 4h close return <= -1.5%; not verified intraminute crashes)")
    print("Saved:", summary_path)
    print("Saved:", rows_path)
    print("Saved:", events_path)
    print("\nInterpretation: activity/range can flag a volatile state, but these features do not by themselves prove DOWN direction.")
    print("Use Binance 1m OHLC to test TP/SL ordering, fees and realistic entries; this script cannot do that.")


if __name__ == "__main__":
    main()
