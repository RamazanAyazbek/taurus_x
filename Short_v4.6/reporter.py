import os

import pandas as pd


# Сохраняем порядок и названия столбцов исходного CSV v7.3.
TRADE_COLUMNS = [
    "signal_time", "entry_time", "exit_time", "type", "entry_price",
    "exit_price", "hold_minutes", "net_pnl_pct", "exit_reason",
    "mfe_pct", "mae_pct", "mfe_time_min", "mae_time_min",
    "confirmation_delay_min", "confirmation_move_pct", "entry_dOI",
    "entry_dPrice", "entry_volume", "entry_taker_buy", "entry_zone",
]

# Новые диагностические данные располагаются строго после прежних столбцов.
EXTRA_TRADE_COLUMNS = [
    "confirmation_price", "entry_drift_pct", "entry_price_source",
    "distance_to_s1_pct", "s1_low", "s1_high",
]


def _slug(value):
    return f"{float(value):g}".replace(".", "p").replace("-", "m")


def build_output_path(trades, config):
    outcomes = [trade.get("result") for trade in trades]
    wins, losses = outcomes.count("WIN"), outcomes.count("LOSS")
    wr = _slug(round(wins / (wins + losses) * 100, 1)) if wins + losses else "na"
    filename = (
        f"{config.RESULT_PREFIX}_{config.STRATEGY_VERSION}"
        f"_n{len(trades)}_wr{wr}.xlsx"
    )
    return os.path.join(config.RESULTS_DIR, filename)


def export_analysis(trades, config, s1_rejections=None, filter_counts=None):
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    output = build_output_path(trades, config)

    # В начале Trades всегда прежние 20 колонок, даже если сделок нет.
    trade_columns = TRADE_COLUMNS + EXTRA_TRADE_COLUMNS
    additional = [
        column for trade in trades for column in trade
        if column not in trade_columns and column != "result"
    ]
    trade_columns += list(dict.fromkeys(additional))
    trades_df = pd.DataFrame(trades).reindex(columns=trade_columns)

    rejects_df = pd.DataFrame(s1_rejections or [])
    outcomes = [trade.get("result") for trade in trades]
    tp, sl, timeout = (
        outcomes.count("WIN"), outcomes.count("LOSS"), outcomes.count("TIMEOUT")
    )
    winrate = f"{tp / (tp + sl) * 100:.1f}%" if tp + sl else "N/A"
    net = sum(float(trade["net_pnl_pct"]) for trade in trades)

    summary = [
        ["Версия", config.STRATEGY_VERSION],
        ["Позиция", "SHORT"],
        ["Сделок", len(trades)],
        ["Take-Profit", tp],
        ["Stop-Loss", sl],
        ["Timeout", timeout],
        ["Win Rate TP/(TP+SL)", winrate],
        ["Сумма Net PnL, %", round(net, 2)],
        ["S1 фильтр", bool(config.SUPPORT_FILTER_ENABLED)],
        ["S1 порог, %", float(config.SUPPORT_NEAR_PCT)],
        ["S1 пауза, минуты", int(config.SUPPORT_COOLDOWN_MINUTES)],
        ["S1 повторная проверка по Binance OPEN", bool(config.SUPPORT_RECHECK_AT_ENTRY)],
        ["S1 отклонено", len(rejects_df)],
        ["Источник цены входа", config.ENTRY_PRICE_SOURCE],
        ["Задержка цены, минуты", int(config.ENTRY_DELAY_MINUTES)],
        ["Важно", "Сумма процентов без плеча/compounding; Binance OPEN не равен реальному MARKET Fill"],
    ]
    if filter_counts:
        summary.extend(
            [f"Счётчик: {name}", value] for name, value in filter_counts.items()
        )

    # Первый лист — сделки, как в прежнем CSV. Сводка и отказы S1 — отдельно.
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        trades_df.to_excel(writer, sheet_name="Trades", index=False)
        pd.DataFrame(summary, columns=["Показатель", "Значение"]).to_excel(
            writer, sheet_name="Summary", index=False
        )
        (rejects_df if not rejects_df.empty else pd.DataFrame(columns=[
            "signal_time", "confirmation_time", "check_stage", "check_time",
            "sim_entry_price", "confirmation_price", "distance_to_s1_pct",
            "s1_low", "s1_high", "s1_observed_at", "cooldown_until",
            "confirmation_taker_buy", "confirmation_move_pct",
        ])).to_excel(writer, sheet_name="S1_Rejections", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.row_dimensions[1].height = 24
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
            for column in ws.columns:
                letter = column[0].column_letter
                max_length = max((len(str(cell.value or "")) for cell in list(column)[:100]), default=12)
                ws.column_dimensions[letter].width = min(39, max(14, max_length + 2))

    print(
        f"\nSHORT | сделок {len(trades)} | TP {tp} | SL {sl} | "
        f"Timeout {timeout} | WR {winrate} | Net {net:+.2f}%"
    )
    print(f"Отчёт: {output}")
    return output
