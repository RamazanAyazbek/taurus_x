import os
import pandas as pd


def export_analysis(trades, output_csv):
    df = pd.DataFrame(trades)

    if df.empty:
        print("Сделок за указанный период не найдено.")
        return

    wins = df[df.result == "WIN"]
    losses = df[df.result == "LOSS"]
    breakevens = df[df.result == "BE"]
    timeouts = df[df.result == "TIMEOUT"]
    tp_sl_count = len(wins) + len(losses)
    completed_count = tp_sl_count + len(breakevens)

    print("\n==================================================")
    print("📊 TAURUS BACKTEST V6.3 — LONG TREND FILTER")
    print("==================================================")
    print(f"Всего сделок            : {len(df)}")
    print(f"WIN                     : {len(wins)}")
    print(f"LOSS                    : {len(losses)}")
    print(f"BE                      : {len(breakevens)}")
    print(f"TIMEOUT                 : {len(timeouts)}")
    print(f"Winrate (WIN/(WIN+LOSS)): {(len(wins) / tp_sl_count * 100 if tp_sl_count else 0):.1f}%")
    print(f"Completion rate         : {(completed_count / len(df) * 100 if len(df) else 0):.1f}%")
    print(f"Чистый PnL              : {df.net_pnl_pct.sum():+.2f}%")
    print("==================================================\n")

    base_columns = [
        "entry_time", "exit_time", "type", "entry_price", "exit_price",
        "hold_minutes", "net_pnl_pct", "result", "exit_reason",
        "previous_30m_return", "previous_2h_return", "previous_4h_return",
        "previous_12h_return", "previous_48h_return",
        "long_sma_12h_slope_2h_pct", "entry_vol_xmed", "entry_zone",
    ]
    available_columns = [column for column in base_columns if column in df.columns]
    print(df[available_columns].to_string(index=False))

    output_dir = os.path.dirname(output_csv)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n[+] Сохранено в файл: {output_csv}")
