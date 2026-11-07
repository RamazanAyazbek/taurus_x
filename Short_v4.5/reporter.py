import os
import pandas as pd


def _slug(value):
    return f"{float(value):g}".replace(".", "p").replace("-", "m")


def build_output_path(trades, config):
    if trades:
        results = [t["result"] for t in trades]
        wins = results.count("WIN")
        losses = results.count("LOSS")
        wr = _slug(round(wins / (wins + losses) * 100, 1)) if wins + losses else "na"
    else:
        wr = "na"
    filename = (
        f"{config.RESULT_PREFIX}_{config.STRATEGY_VERSION}"
        f"_s1{'on' if config.SUPPORT_FILTER_ENABLED else 'off'}"
        f"_near{_slug(config.SUPPORT_NEAR_PCT)}"
        f"_wait{config.SUPPORT_COOLDOWN_MINUTES}m"
        f"_entry{'bn' + str(config.ENTRY_DELAY_MINUTES) if config.ENTRY_PRICE_SOURCE == 'binance_open' else 'collector'}"
        f"_tp{_slug(config.TP_PCT)}_sl{_slug(config.SL_PCT)}_wr{wr}.xlsx"
    )
    return os.path.join(config.RESULTS_DIR, filename)


def export_analysis(trades, config, s1_rejections=None, filter_counts=None):
    output = build_output_path(trades, config)
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    df = pd.DataFrame(trades)
    if not df.empty:
        df = df.drop(columns=["result"], errors="ignore")
    rejects = pd.DataFrame(s1_rejections or [])
    if trades:
        results = [r["result"] for r in trades]
        tp, sl, timeout = results.count("WIN"), results.count("LOSS"), results.count("TIMEOUT")
        wr = f"{tp / (tp + sl) * 100:.1f}%" if tp + sl else "N/A"
        net = sum(float(r["net_pnl_pct"]) for r in trades)
    else:
        tp = sl = timeout = 0
        wr = "N/A"
        net = 0.0
    summary = [
        ["Версия", config.STRATEGY_VERSION],
        ["Позиция", "SHORT"],
        ["Сделок", len(trades)],
        ["Take-Profit", tp],
        ["Stop-Loss", sl],
        ["Timeout", timeout],
        ["Win Rate TP/(TP+SL)", wr],
        ["Сумма Net PnL, %", round(net, 2)],
        ["S1 фильтр", bool(config.SUPPORT_FILTER_ENABLED)],
        ["S1 порог, %", float(config.SUPPORT_NEAR_PCT)],
        ["S1 пауза, минуты", int(config.SUPPORT_COOLDOWN_MINUTES)],
        ["S1 повторная проверка по Binance OPEN", bool(config.SUPPORT_RECHECK_AT_ENTRY)],
        ["S1 отклонено", len(rejects)],
        ["Источник цены входа", config.ENTRY_PRICE_SOURCE],
        ["Задержка цены, минуты", int(config.ENTRY_DELAY_MINUTES)],
        ["Важно", "Это сумма % без compounding и плеча; Binance 1m OPEN — не точный рыночный fill"],
    ]
    if filter_counts:
        summary.extend([[f"Счётчик: {name}", value] for name, value in filter_counts.items()])

    # One Excel workbook; all detailed columns stay out of console.
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(summary, columns=["Показатель", "Значение"]).to_excel(writer, sheet_name="Summary", index=False)
        (df if not df.empty else pd.DataFrame(columns=[
            "signal_time", "entry_time", "exit_time", "type", "entry_price",
            "confirmation_price", "entry_drift_pct", "exit_price", "net_pnl_pct", "exit_reason"
        ])).to_excel(writer, sheet_name="Trades", index=False)
        (rejects if not rejects.empty else pd.DataFrame(columns=[
            "signal_time", "confirmation_time", "distance_to_s1_pct", "cooldown_until"
        ])).to_excel(writer, sheet_name="S1_Rejections", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
            for col in ws.columns:
                letter = col[0].column_letter
                width = min(36, max(13, max(len(str(cell.value or "")) for cell in list(col)[:100]) + 2))
                ws.column_dimensions[letter].width = width

    print(f"\nSHORT | сделок {len(trades)} | TP {tp} | SL {sl} | Timeout {timeout} "
          f"| WR {wr} | Net {net:+.2f}%")
    print(f"Отчёт: {output}")
    return output
