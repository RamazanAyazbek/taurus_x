"""Log-only directional diagnostic for SHORT hypotheses; does not replace OHLC backtest.

Run from the project root:
    python research_short_hypotheses.py

It counts non-overlapping candidates and measures subsequent observed log-price returns.
This scan cannot establish TP/SL order inside candles and is only a hypothesis filter.
"""
from pathlib import Path
import numpy as np
import pandas as pd

import config
import short_config
from log_parser import parse_taurus_log
from short_signal_logic import evaluate_short_hypothesis, prepare_short_features

HYPOTHESES = (
    "TREND_CONTINUATION",
    "R1_REJECTION",
    "R1_CONFIRMED_REJECTION",
    "PUMP_THEN_REVERSAL",
    "OI_UNWIND_DOWNTURN",
    "S1_BREAKDOWN",
)
FORWARD_MINUTES = (30, 60, 120, 240)


def add_forward_returns(df):
    out = df.copy()
    t_ns = pd.to_datetime(out["dt"], utc=True).astype("int64").to_numpy()
    prices = out["price"].astype(float).to_numpy()
    for minutes in FORWARD_MINUTES:
        next_idx = np.searchsorted(t_ns, t_ns + minutes * 60 * 1_000_000_000, side="left")
        values = np.full(len(out), np.nan, dtype=float)
        valid = next_idx < len(out)
        safe_idx = np.minimum(next_idx, len(out) - 1)
        age_minutes = (t_ns[safe_idx] - t_ns) / 60_000_000_000
        valid &= age_minutes <= minutes + 30
        values[valid] = (prices[next_idx[valid]] / prices[valid] - 1.0) * 100.0
        out[f"observed_forward_{minutes}m_price_return_pct"] = values
        out[f"observed_forward_{minutes}m_short_return_pct"] = -values
    return out


def select_with_cooldown(candidates, cooldown_minutes):
    selected_indices = []
    last_selected_dt = None
    for idx, row in candidates.iterrows():
        if last_selected_dt is None or (row["dt"] - last_selected_dt).total_seconds() / 60 >= cooldown_minutes:
            selected_indices.append(idx)
            last_selected_dt = row["dt"]
    return candidates.loc[selected_indices].copy()


def main():
    log_path = Path(config.LOG_FILE)
    df = parse_taurus_log(log_path)
    if df.empty:
        raise SystemExit(f"No price rows parsed from {log_path}")

    df = prepare_short_features(df, short_config)
    df = add_forward_returns(df)
    market_return = (df.iloc[-1]["price"] / df.iloc[0]["price"] - 1) * 100

    print("\nTAURUS SHORT SCAN | directional log diagnostic, NOT TP/SL PnL")
    print(f"Rows: {len(df):,} | Local period: {df['dt_local'].min()} -> {df['dt_local'].max()}")
    print(f"First-to-last BTC return: {market_return:+.2f}% | Cooldown: {short_config.SHORT_REENTRY_COOLDOWN_MINUTES}m")
    print("Fixed-horizon returns use the next available log observation; gaps can shift the actual horizon.")
    print("\nHypothesis                Raw  Selected   n60   mean60  fav60   n240  mean240  fav240")
    print("-" * 84)

    summary = []
    detail_frames = []
    for hypothesis in HYPOTHESES:
        mask = []
        for _, row in df.iterrows():
            mask.append(evaluate_short_hypothesis(row, short_config, hypothesis) is not None)
        raw = df.loc[mask].copy()
        raw["short_hypothesis"] = hypothesis

        if len(raw):
            chosen = select_with_cooldown(raw, short_config.SHORT_REENTRY_COOLDOWN_MINUTES)
            raw["selected_after_cooldown"] = raw.index.isin(chosen.index)
            detail_frames.append(raw)
        else:
            chosen = raw.copy()
            raw["selected_after_cooldown"] = pd.Series(dtype=bool)

        row_summary = {
            "hypothesis": hypothesis,
            "raw_candidates": int(len(raw)),
            "after_cooldown": int(len(chosen)),
            "cooldown_minutes": int(short_config.SHORT_REENTRY_COOLDOWN_MINUTES),
        }
        for minutes in FORWARD_MINUTES:
            col = f"observed_forward_{minutes}m_short_return_pct"
            values = pd.to_numeric(chosen[col], errors="coerce").dropna()
            row_summary[f"n_{minutes}m"] = int(len(values))
            row_summary[f"mean_short_return_{minutes}m_pct"] = float(values.mean()) if len(values) else np.nan
            row_summary[f"median_short_return_{minutes}m_pct"] = float(values.median()) if len(values) else np.nan
            row_summary[f"favourable_close_rate_{minutes}m_pct"] = float((values > 0).mean() * 100) if len(values) else np.nan
        summary.append(row_summary)

        print(
            f"{hypothesis:<25} {len(raw):4d} {len(chosen):9d} "
            f"{row_summary['n_60m']:4d} {row_summary['mean_short_return_60m_pct']:+8.3f}% "
            f"{row_summary['favourable_close_rate_60m_pct']:5.1f}% "
            f"{row_summary['n_240m']:5d} {row_summary['mean_short_return_240m_pct']:+8.3f}% "
            f"{row_summary['favourable_close_rate_240m_pct']:5.1f}%"
        )

    summary_df = pd.DataFrame(summary)
    summary_path = Path("data/short_hypothesis_scan_summary.csv")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    detail_path = Path("data/short_hypothesis_scan_details.csv")
    if detail_frames:
        detail_df = pd.concat(detail_frames, ignore_index=True)
        detail_df["cooldown_minutes"] = int(short_config.SHORT_REENTRY_COOLDOWN_MINUTES)
        detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(detail_path, index=False, encoding="utf-8-sig")

    print("\nSaved summary CSV:", summary_path)
    print("Saved candidate detail CSV:", detail_path)
    print("Details include all raw candidates; selected_after_cooldown marks the rows used in summary.")
    print("Use main.py with Binance 1m OHLC for actual TP/SL/BE backtest; this scan does not simulate trades.")


if __name__ == "__main__":
    main()
