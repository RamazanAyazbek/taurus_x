import pandas as pd


def export_analysis(trades, output_csv):
    df = pd.DataFrame(trades)
    if df.empty:
        print("Сделок за указанный период не найдено.")
        return

    wins = df[df.result == "WIN"]
    losses = df[df.result == "LOSS"]
    timeouts = df[df.result == "TIMEOUT"]
    breakeven = df[df.result == "BREAKEVEN"] if "result" in df else df.iloc[0:0]
    completed = len(wins) + len(losses)
    closed = completed + len(breakeven)

    print("\n==================================================")
    print("📊 TAURUS BACKTEST V5.7")
    print("==================================================")
    print(f"Всего сделок            : {len(df)}")
    print(f"WIN                     : {len(wins)}")
    print(f"LOSS                    : {len(losses)}")
    print(f"BREAKEVEN               : {len(breakeven)}")
    print(f"TIMEOUT                 : {len(timeouts)}")
    print(f"Winrate (без BE)        : {(len(wins) / completed * 100 if completed else 0):.1f}%")
    print(f"Completion rate         : {(closed / len(df) * 100):.1f}%")
    print(f"Чистый PnL              : {df.net_pnl_pct.sum():+.2f}%")
    print("--------------------------------------------------")
    for side in ("LONG", "SHORT"):
        side_df = df[df["type"] == side]
        if side_df.empty:
            continue
        side_wins = int((side_df["result"] == "WIN").sum())
        side_losses = int((side_df["result"] == "LOSS").sum())
        side_be = int((side_df["result"] == "BREAKEVEN").sum())
        side_closed = side_wins + side_losses
        side_wr = side_wins / side_closed * 100 if side_closed else 0.0
        print(
            f"{side:<6} trades={len(side_df):2d} | WIN={side_wins:2d} "
            f"LOSS={side_losses:2d} BE={side_be:2d} | "
            f"WR={side_wr:5.1f}% | PnL={side_df.net_pnl_pct.sum():+.2f}%"
        )
    print("==================================================\n")

    base_columns = [
        "entry_time", "exit_time", "type", "entry_price", "exit_price",
        "hold_minutes", "net_pnl_pct", "result", "exit_reason",
        "entry_vol_xmed", "entry_dOI", "entry_dPrice", "entry_volume",
        "entry_taker_buy", "entry_zone", "short_term_momentum_return",
        "previous_30m_return", "previous_2h_return", "previous_4h_return",
    ]
    available_columns = [c for c in base_columns if c in df.columns]
    print(df[available_columns].to_string(index=False))
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n[+] Сохранено в файл: {output_csv}")
