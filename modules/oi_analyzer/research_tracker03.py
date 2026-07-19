import os
import time
import threading
from datetime import datetime, timezone, timedelta
from core.binance_client import BinanceFuturesClient

TRACKER_LOG_PATH = "storage/oi/logs/03_tracker.log"
research_counter = 0
counter_lock = threading.Lock()

def _track_price_job(client: BinanceFuturesClient, start_price: float, start_oi: float, start_z: float,
                     trigger_phase: str, res_id: int):
    start_time_ts = time.time()
    duration_limit = 4 * 3600
    tz_gmt5 = timezone(timedelta(hours=5))

    while True:
        try:
            time.sleep(300)
            current = client.get_current_ticker(symbol="BTCUSDT")

            elapsed = time.time() - start_time_ts
            price_change_pct = ((current["price"] - start_price) / start_price) * 100
            oi_change_pct = ((current["open_interest"] - start_oi) / start_oi) * 100

            if elapsed >= duration_limit or abs(price_change_pct) >= 2.0:
                # Временные метки переводим в читаемый формат GMT+5
                start_time_str = datetime.fromtimestamp(start_time_ts, tz=tz_gmt5).strftime("%Y-%m-%d %H:%M:%S GMT+5")
                finish_time_str = datetime.fromtimestamp(current["timestamp"], tz=tz_gmt5).strftime("%Y-%m-%d %H:%M:%S GMT+5")
                duration_str = str(timedelta(seconds=int(elapsed)))

                status_msg = "Достигнут таргет цены" if abs(price_change_pct) >= 2.0 else "Истекло время тайм-аута (4ч)"
                hypothesis = "ПОДТВЕРЖДЕНА" if (
                    (trigger_phase == "[BULLISH_REINFORCEMENT]" and price_change_pct > 0) or
                    (trigger_phase == "[BEARISH_REINFORCEMENT]" and price_change_pct < 0)
                ) else "НЕ ПОДТВЕРЖДЕНА / СМАЗАНА"

                log_block = (
                    f"=== ЗАВЕРШЕНО ИССЛЕДОВАНИЕ #{res_id} ===\n"
                    f"Время старта : {start_time_str} | Цена: {start_price:,.2f} | OI: {int(start_oi):,} (Z-Score: {start_z:.2f})\n"
                    f"Время финиша : {finish_time_str} | Цена: {current['price']:,.2f} | OI: {int(current['open_interest']):,}\n"
                    f"Длительность : {duration_str} ({status_msg})\n"
                    f"[СТАРТОВЫЙ ТРИГГЕР]: Фаза {trigger_phase}.\n"
                    f"[ИЗМЕНЕНИЯ ЗА ТЕСТ]: Цена {price_change_pct:+.2f}%. OI {oi_change_pct:+.2f}%.\n"
                    f"[АНАЛИЗ ДАННЫХ]: Гипотеза направления цены {hypothesis}.\n"
                    f"=================================\n\n"
                )

                with open(TRACKER_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(log_block)
                break
        except Exception:
            continue

def check_and_track(analysis_result: dict, client: BinanceFuturesClient):
    global research_counter
    phase = analysis_result["phase"]
    metrics = analysis_result["metrics"]

    if metrics["is_anomaly"] or phase in ["[BULLISH_REINFORCEMENT]", "[BEARISH_REINFORCEMENT]"]:
        with counter_lock:
            research_counter += 1
            current_id = research_counter
        try:
            current_ticker = client.get_current_ticker("BTCUSDT")
            t = threading.Thread(
                target=_track_price_job,
                args=(client, current_ticker["price"], current_ticker["open_interest"], metrics["z_score"], phase, current_id),
                daemon=True
            )
            t.start()
        except Exception:
            pass