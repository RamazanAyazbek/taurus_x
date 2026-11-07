"""Offline audit of prior trade entries against V6.3 entry filters.

This is NOT a new TP/SL backtest. It asks only whether each previously recorded
entry timestamp would pass the new entry filters. The changed signal timing/state
lock means the true V6.3 trade set must be regenerated with 1m klines.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import config
from log_parser import parse_taurus_log
from signal_logic import prepare_long_features


def main():
    log_path = Path(config.LOG_FILE)
    csv_path = Path("data/backtest_details_v6.2.csv")
    out_path = Path("data/v6.2_entry_filter_audit.csv")
    if not log_path.exists() or not csv_path.exists():
        raise FileNotFoundError(f"Required audit input missing: {log_path} / {csv_path}")

    logs = prepare_long_features(parse_taurus_log(str(log_path)), config)
    trades = pd.read_csv(csv_path)
    log_times_ns = pd.DatetimeIndex(logs["dt"]).asi8
    audit_rows = []

    for _, trade in trades.iterrows():
        target = pd.Timestamp(trade["entry_time"]).tz_localize("Asia/Almaty").tz_convert("UTC")
        pos = int(np.argmin(np.abs(log_times_ns - target.value)))
        row = logs.iloc[pos]
        context = {
            name: (float(row[name]) if pd.notna(row.get(name)) else None)
            for name in [
                "previous_30m_return", "previous_2h_return", "previous_4h_return",
                "previous_12h_return", "previous_48h_return",
                "long_sma_12h_slope_2h_pct", "long_price_vs_sma_12h_pct",
            ]
        }
        reasons = []
        ratio = float(row.get("vol_xmed", np.nan))
        if not np.isfinite(ratio) or ratio < config.CURRENT_VOLUME_XMED_MIN:
            reasons.append(f"vol_xmed<{config.CURRENT_VOLUME_XMED_MIN:g}")

        r2h, r4h, r30m = context["previous_2h_return"], context["previous_4h_return"], context["previous_30m_return"]
        if r2h is None or r4h is None:
            reasons.append("missing_2h_or_4h_history")
        else:
            if r4h < config.PREVIOUS_4H_RETURN_MIN:
                reasons.append("4h_return_below_min")
            if r4h > config.PREVIOUS_4H_RETURN_MAX:
                reasons.append("4h_return_above_max")
            if r2h < config.PREVIOUS_2H_RETURN_MIN:
                reasons.append("2h_return_below_min")
        if r30m is None or r30m > config.PREVIOUS_30M_RETURN_MAX:
            reasons.append("30m_return_missing_or_above_max")
        if float(row.get("taker_buy", np.inf)) > config.TAKER_BUY_MAX:
            reasons.append("taker_buy_above_max")

        slope = context["long_sma_12h_slope_2h_pct"]
        if config.ENABLE_LONG_TREND_FILTER and (
            slope is None or slope <= config.LONG_TREND_MIN_SMA_SLOPE_PCT
        ):
            reasons.append("12h_SMA_slope_not_strongly_positive")
        zone = str(row.get("in_zone", "NONE") or "NONE").strip().upper()
        if config.ENABLE_LONG_R1_REJECTION and zone.startswith("R1"):
            reasons.append("R1_resistance_area")

        audit_rows.append({
            "entry_time": trade["entry_time"],
            "old_result": trade["result"],
            "old_net_pnl_pct": trade["net_pnl_pct"],
            "entry_price": trade["entry_price"],
            "entry_zone": zone,
            "entry_vol_xmed": ratio,
            **context,
            "candidate_pass": len(reasons) == 0,
            "filter_rejection_reasons": "|".join(reasons) if reasons else "PASS",
        })

    result = pd.DataFrame(audit_rows)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")
    kept = result[result["candidate_pass"]]
    print("OFFLINE HISTORICAL ENTRY FILTER AUDIT (not a new TP/SL backtest)")
    print(f"Prior entries reviewed: {len(result)}")
    print(f"Entries passing V6.3 filters: {len(kept)}")
    if not kept.empty:
        print("Prior outcomes among entries that pass: ", kept["old_result"].value_counts().to_dict())
        print(f"Historical PnL sum of retained old trades (not a V6.3 result): {kept['old_net_pnl_pct'].sum():+.2f}%")
    print("\nLast four previously recorded entries:")
    print(result.tail(4)[["entry_time", "old_result", "entry_zone", "entry_vol_xmed", "long_sma_12h_slope_2h_pct", "candidate_pass", "filter_rejection_reasons"]].to_string(index=False))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
