import os
import queue
import collections
from datetime import datetime, timezone, timedelta
from modules.oi_analyzer.history_manager import HistoryManager
from modules.oi_analyzer.calculations import calculate_metrics

STRATEGY_LOG_PATH = "storage/oi/logs/02_strategy.log"
os.makedirs(os.path.dirname(STRATEGY_LOG_PATH), exist_ok=True)

# Инициализация внутренних буферов и состояний фаз
if not hasattr(HistoryManager, "_buffer_60m"):
    HistoryManager._buffer_60m = collections.deque(maxlen=5)
if not hasattr(HistoryManager, "_current_phase"):
    HistoryManager._current_phase = "[INIT]"
if not hasattr(HistoryManager, "_phase_hold_counter"):
    HistoryManager._phase_hold_counter = 0

MIN_PHASE_DURATION = 3


def process_strategy(raw_data: dict, main_queue: queue.Queue = None) -> dict:
    tz_gmt5 = timezone(timedelta(hours=5))
    now_local = datetime.now(tz_gmt5)

    current_oi = float(raw_data.get("open_interest", 0.0))
    current_price = float(raw_data.get("price", 0.0))

    # Добавляем точку в буфер
    HistoryManager._buffer_60m.append({"price": current_price, "open_interest": current_oi})
    history = HistoryManager.load_history()

    # Определение опорных точек для 60-минутного окна
    if len(HistoryManager._buffer_60m) < 5:
        init_price = current_price
        init_oi = history[-4]["open_interest"] if len(history) >= 4 else current_oi
        is_init = True
    else:
        base = HistoryManager._buffer_60m[0]
        init_price, init_oi = base["price"], base["open_interest"]
        is_init = False

    # Математический расчет
    res = calculate_metrics(current_oi, history, current_price, init_price, init_oi)

    # Логика фаз
    proposed_phase = "[MARKET_SILENCE]"
    if not is_init and abs(res["price_pct"]) >= 0.15 and abs(res["oi_pct"]) >= 0.20:
        if (res["price_pct"] > 0 and res["oi_pct"] < 0) or (res["price_pct"] < 0 and res["oi_pct"] > 0):
            proposed_phase = "[DIVERGENT_CHOP]"
        elif res["price_pct"] > 0 and res["oi_pct"] > 0:
            proposed_phase = "[BULLISH_PRESSURE]"
        elif res["price_pct"] < 0 and res["oi_pct"] < 0:
            proposed_phase = "[BEARISH_REINFORCEMENT]"

    # Фильтр чехарды фаз (гистерезис)
    signal_sent_str = "НЕТ"
    old_phase = HistoryManager._current_phase

    if proposed_phase != HistoryManager._current_phase:
        if HistoryManager._phase_hold_counter > 0:
            HistoryManager._phase_hold_counter -= 1
        else:
            HistoryManager._current_phase = proposed_phase
            if HistoryManager._current_phase != "[MARKET_SILENCE]":
                HistoryManager._phase_hold_counter = MIN_PHASE_DURATION
            signal_sent_str = f"ДА (Смена фазы с {old_phase} на {HistoryManager._current_phase})"
    else:
        if HistoryManager._current_phase != "[MARKET_SILENCE]":
            HistoryManager._phase_hold_counter = MIN_PHASE_DURATION

    # Сохраняем в скользящее окно кэша жесткого диска
    HistoryManager.update_sliding_window(current_oi)

    # 1. ЗАПИСЬ ВСЕГО ТЕСТА В СВОЙ ЛОГ-ФАЙЛ (В терминал это НЕ идет)
    log_block = (
        f"--- АНАЛИЗ РЫНКА OI (GMT+5) ---\n"
        f"Время: {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Медиана (30д): {res['median']:,.0f} | Арифм. Среднее (30д): {res['mean']:,.0f}\n"
        f"Текущий OI: {current_oi:,} (Отклонение: {res['deviation'] * 100:+.2f}% | Z-Score: {res['z_score']})\n"
        f"Текущая Цена: {current_price:,.2f}\n"
        f"Сравнение (за последние 60 минут):\n"
        f"  - Цена: {init_price:,.2f} -> {current_price:,.2f} ({res['price_pct']:+.2f}%)\n"
        f"  - OI:   {init_oi:,} -> {current_oi:,} ({res['oi_pct']:+.2f}%)\n"
        f"Текущая фаза: {HistoryManager._current_phase}\n"
        f"Сигнал отправлен в Main: {signal_sent_str}\n"
        f"------------------------\n"
    )
    with open(STRATEGY_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(log_block)

    # 2. ВЫВОД В ТЕРМИНАЛ ТОЛЬКО АНОМАЛИЙ ИЛИ ВАЖНЫХ СИГНАЛОВ
    if res["is_anomaly"] or HistoryManager._current_phase in ["[BULLISH_PRESSURE]", "[BEARISH_REINFORCEMENT]",
                                                              "[DIVERGENT_CHOP]"]:
        if old_phase != HistoryManager._current_phase or res["is_anomaly"]:
            print(f"\n🚨 [🚨 ВНИМАНИЕ: АНОМАЛИЯ НА РЫНКЕ OI (GMT+5)] | {now_local.strftime('%H:%M:%S')}")
            print(
                f"   Фаза: {HistoryManager._current_phase} | Z-Score: {res['z_score']} (Отклонение: {res['deviation'] * 100:+.2f}%)")
            print(
                f"   Изменение за час: Цена {res['price_pct']:+.2f}%, OI {res['oi_pct']:+.2f}% (Цена: {current_price:,.2f})\n")

    # Пересылка в очередь
    if signal_sent_str != "НЕТ" and main_queue is not None:
        try:
            main_queue.put_nowait({
                "event": "OI_PHASE_CHANGED",
                "phase": HistoryManager._current_phase,
                "timestamp": now_local.isoformat()
            })
        except Exception:
            pass

    return {
        "phase": HistoryManager._current_phase,
        "metrics": res
    }