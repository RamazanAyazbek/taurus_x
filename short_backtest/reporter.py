"""Write full trade analysis to CSV and keep terminal output compact."""
from pathlib import Path
import pandas as pd


# Only these core columns are shown in the terminal. The CSV retains every field.
_TERMINAL_MAX_TRADES = 20
_BASE_COLUMNS = [
    "entry_time", "exit_time", "type", "short_hypothesis", "entry_price", "exit_price",
    "hold_minutes", "gross_price_return_pct", "fees_pct", "net_pnl_pct", "result",
    "exit_reason", "entry_vol_xmed", "entry_dOI", "entry_dPrice", "entry_volume",
    "entry_taker_buy", "entry_zone", "short_zone_position", "short_return_10m_pct",
    "short_return_30m_pct", "short_return_2h_pct", "short_return_4h_pct",
    "short_term_momentum_return", "previous_30m_return", "previous_2h_return",
    "previous_4h_return", "short_zone_low", "short_zone_high", "short_reported_high",
    "short_rejection_from_high_pct", "trade_MFE_pct", "trade_MAE_pct",
]


def _metric_line(label, frame):
    if frame.empty:
        print(f"{label:<25}: no trades")
        return

    outcomes = frame["result"].fillna("").astype(str)
    wins = int((outcomes == "WIN").sum())
    losses = int((outcomes == "LOSS").sum())
    breakeven = int((outcomes == "BREAKEVEN").sum())
    timeouts = int((outcomes == "TIMEOUT").sum())
    resolved_tp_sl = wins + losses
    winrate = wins / resolved_tp_sl * 100 if resolved_tp_sl else 0.0

    pnl = pd.to_numeric(frame["net_pnl_pct"], errors="coerce").fillna(0.0)
    positive_pnl = float(pnl[pnl > 0].sum())
    negative_pnl = float(-pnl[pnl < 0].sum())
    profit_factor = positive_pnl / negative_pnl if negative_pnl > 0 else float("inf")

    # Drawdown on a cumulative sum of equal-sized underlying-price returns (not account equity).
    equity_like = pnl.cumsum().to_numpy(dtype=float)
    running_peak = pd.Series([0.0, *equity_like]).cummax().to_numpy()[1:]
    max_drawdown = float((running_peak - equity_like).max()) if len(equity_like) else 0.0

    print(
        f"{label:<25}: n={len(frame):3d} | TP/SL/BE/TO={wins}/{losses}/{breakeven}/{timeouts} "
        f"| WR={winrate:5.1f}%* | netΣ={pnl.sum():+7.3f}% "
        f"| avg={pnl.mean():+7.3f}% | PF={profit_factor:.2f} | seqDD={max_drawdown:.3f}%"
    )


def _print_trade_table(df):
    if df.empty:
        return
    shown = df.sort_values("entry_time", kind="stable")
    omitted = max(0, len(shown) - _TERMINAL_MAX_TRADES)
    if omitted:
        # Most recent trade rows are typically the most relevant during parameter experiments.
        shown = shown.tail(_TERMINAL_MAX_TRADES)
        print(f"\nRecent trades ({len(shown)} of {len(df)}; {omitted} earlier rows omitted from terminal):")
    else:
        print("\nTrades (compact view):")

    result_abbrev = {"WIN": "TP", "LOSS": "SL", "BREAKEVEN": "BE", "TIMEOUT": "TIMEOUT"}
    rows = []
    for _, row in shown.iterrows():
        entry_time = str(row.get("entry_time", ""))
        exit_time = str(row.get("exit_time", ""))
        result = str(row.get("result", ""))
        rows.append({
            "ENTRY (Almaty)": entry_time,
            "EXIT (Almaty)": exit_time,
            "SIDE": str(row.get("type", "")),
            "OUT": result_abbrev.get(result, result),
            "ENTRY PX": _fmt_price(row.get("entry_price")),
            "EXIT PX": _fmt_price(row.get("exit_price")),
            "HOLD": _fmt_minutes(row.get("hold_minutes")),
            "NET": _fmt_pct(row.get("net_pnl_pct")),
        })
    print(pd.DataFrame(rows).to_string(index=False))


def _fmt_price(value):
    try:
        return f"{float(value):,.1f}".replace(",", "")
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value):
    try:
        return f"{float(value):+.3f}%"
    except (TypeError, ValueError):
        return "-"


def _fmt_minutes(value):
    try:
        return f"{int(float(value))}m"
    except (TypeError, ValueError):
        return "-"


def export_analysis(trades, output_csv):
    df = pd.DataFrame(trades)
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if df.empty:
        pd.DataFrame(columns=_BASE_COLUMNS).to_csv(output_path, index=False, encoding="utf-8-sig")
        print("\nTAURUS BACKTEST | no trades for this configuration")
        print(f"Full CSV saved: {output_path}")
        return

    # Save all columns before printing anything: terminal formatting never discards detail.
    ordered = [c for c in _BASE_COLUMNS if c in df.columns]
    ordered += [c for c in df.columns if c not in ordered]
    df[ordered].to_csv(output_path, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 94)
    print("TAURUS BACKTEST | SUMMARY")
    print("=" * 94)
    _metric_line("ALL", df)
    for side in ("LONG", "SHORT"):
        side_rows = df[df["type"] == side] if "type" in df.columns else df.iloc[0:0]
        _metric_line(side, side_rows)

    if "short_hypothesis" in df.columns and "type" in df.columns:
        candidates = df[df["type"] == "SHORT"]
        candidates = candidates[candidates["short_hypothesis"].fillna("").astype(str).ne("")]
        for hypothesis, subset in candidates.groupby("short_hypothesis", sort=False):
            _metric_line(str(hypothesis), subset)

    _print_trade_table(df)
    print("\n* WR = TP / (TP + SL); BE and TIMEOUT are excluded from this ratio.")
    print("Net/avg/seqDD sum per-trade underlying-price percentage returns after estimated fees; they are NOT account ROI.")
    print("Leverage, position sizing, funding, slippage and compounding are not modeled.")
    print(f"Full detailed CSV saved: {output_path}")
