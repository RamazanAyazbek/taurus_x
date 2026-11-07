import os
import pandas as pd


def _number_slug(value):
    return f"{float(value):g}".replace(".", "p").replace("-", "m")


def build_output_path(trades, config):
    """Name the one output ledger with strategy, TP/SL parameters and realized winrate."""
    if trades:
        df = pd.DataFrame(trades)
        wins = int((df["result"] == "WIN").sum())
        losses = int((df["result"] == "LOSS").sum())
        resolved = wins + losses
        winrate_slug = _number_slug(round(wins / resolved * 100, 1)) if resolved else "na"
    else:
        winrate_slug = "na"

    filename = (
        f"{config.RESULT_PREFIX}_{config.STRATEGY_VERSION}"
        f"_rebound{_number_slug(config.CONFIRMATION_MAX_REBOUND_PCT)}"
        f"_tbmin{_number_slug(config.CONFIRMATION_MIN_TAKER_BUY)}"
        f"_tbmax{_number_slug(config.CONFIRMATION_MAX_TAKER_BUY) if getattr(config, 'CONFIRMATION_MAX_TAKER_BUY_ENABLED', False) else 'off'}"
        f"_down{_number_slug(config.CONFIRMATION_MIN_DOWN_MOVE_PCT) if getattr(config, 'CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED', False) else 'off'}"
        f"_tp{_number_slug(config.TP_PCT)}"
        f"_sl{_number_slug(config.SL_PCT)}"
        f"_to{int(config.TIMEOUT_MINUTES)}m"
        f"_s1{'on' if config.SUPPORT_RISK_ENABLED else 'off'}"
        f"_tbr{'on' if config.TAKER_RISE_RISK_ENABLED else 'off'}"
        f"_pe{int(config.PREENTRY_DELAY_MINUTES) if config.PREENTRY_CHECK_ENABLED else 'off'}"
        f"_wr{winrate_slug}.csv"
    )
    return os.path.join(config.RESULTS_DIR, filename)


def export_analysis(trades, config):
    output_csv = build_output_path(trades, config)
    os.makedirs(config.RESULTS_DIR, exist_ok=True)

    # WIN/LOSS are internal simulator states only. Final output uses exit reason
    # labels once: Take-Profit, Stop-Loss, or Timeout.
    columns = [
        "signal_time", "entry_time", "exit_time", "type", "entry_price",
        "exit_price", "hold_minutes", "net_pnl_pct", "exit_reason",
        "mfe_pct", "mae_pct", "mfe_time_min", "mae_time_min",
        "confirmation_delay_min", "confirmation_move_pct", "entry_dOI",
        "entry_dPrice", "entry_volume", "entry_taker_buy", "entry_zone",
        "confirmation_price", "support_distance_pct", "taker_buy_delta_pp",
        "preentry_move_pct", "size_multiplier", "weighted_net_pnl_pct",
    ]
    df = pd.DataFrame(trades)

    print("\n==================================================")
    print("TAURUS SHORT | REALISTIC 1m BINANCE BACKTEST")
    print("==================================================")
    if df.empty:
        print("Всего сделок            : 0")
        print("Take-Profit              : 0")
        print("Stop-Loss                : 0")
        print("Timeout                  : 0")
        print("Winrate                  : N/A")
        print("Чистый PnL               : +0.00%")
        df = pd.DataFrame(columns=columns)
    else:
        tp_count = int((df["result"] == "WIN").sum())
        sl_count = int((df["result"] == "LOSS").sum())
        timeout_count = int((df["result"] == "TIMEOUT").sum())
        resolved = tp_count + sl_count
        winrate = tp_count / resolved * 100 if resolved else 0.0
        print(f"Всего сделок            : {len(df)}")
        print(f"Take-Profit              : {tp_count}")
        print(f"Stop-Loss                : {sl_count}")
        print(f"Timeout                  : {timeout_count}")
        print(f"Winrate (TP/(TP+SL))     : {winrate:.1f}%")
        print(f"Completion rate          : {resolved / len(df) * 100:.1f}%")
        print(f"Чистый PnL               : {df['net_pnl_pct'].sum():+.2f}% (сумма %, не equity-compounded)")
        print(f"С учётом размера позиции : {df['weighted_net_pnl_pct'].sum():+.2f}% (условный взвешенный PnL, не ROI счёта)")
    print("==================================================\n")
    print(df[columns].to_string(index=False))
    df[columns].to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n[+] Итоговый файл: {output_csv}")
    return output_csv
