import pandas as pd


def export_analysis(trades, output_csv):
    df = pd.DataFrame(trades)

    if df.empty:
        print("Сделок за указанный период не найдено.")
        return

    wins = df[df.result == "WIN"]
    losses = df[df.result == "LOSS"]
    timeouts = df[df.result == "TIMEOUT"]
    completed = len(wins) + len(losses)

    print("\n==================================================")
    print("📊 TAURUS BACKTEST V5")
    print("==================================================")
    print(f"Всего сделок            : {len(df)}")
    print(f"WIN                     : {len(wins)}")
    print(f"LOSS                    : {len(losses)}")
    print(f"TIMEOUT                 : {len(timeouts)}")
    print(f"Winrate                 : {(len(wins) / completed * 100 if completed else 0):.1f}%")
    print(f"Completion rate         : {(completed / len(df) * 100):.1f}%")
    print(f"Чистый PnL              : {df.net_pnl_pct.sum():+.2f}%")
    print("==================================================\n")

    base_columns = [
        "entry_time", "exit_time", "type", "entry_price", "exit_price",
        "hold_minutes", "net_pnl_pct", "result", "exit_reason"
    ]

    available_columns = [c for c in base_columns if c in df.columns]
    print(df[available_columns].to_string(index=False))

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n[+] Сохранено в файл: {output_csv}")
