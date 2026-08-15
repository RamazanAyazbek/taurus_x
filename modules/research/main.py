import time
import traceback
import os
import json, requests
from datetime import datetime, timedelta

# Importing your modules
from baseline_calculator import BaselineCalculator
from asia_session_scanner import TodaySessionScanner
from level_detector import LevelDetector
from analyze_live_market import BinanceFuturesLivePrinter

# System Settings
SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
TIMEZONE_OFFSET = 5
BASELINE_FILE = "baseline_metrics.json"

BASELINE_UPDATE_INTERVAL = 604800  # 7 days in seconds
LIVE_MONITOR_INTERVAL = 600        # 10 minutes in seconds

def print_header(title: str):
    """ Clean visual separator for system events """
    print("\n" + "="*70)
    print(f" 🔷 {title} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)


def run_baseline():
    try:
        # 1. Проверяем наличие файла с метриками
        if os.path.exists(BASELINE_FILE):
            try:
                with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                period_end_str = data.get("period_end")

                if period_end_str:
                    period_end_dt = datetime.strptime(period_end_str, "%Y-%m-%d %H:%M")
                    days_passed = (datetime.now() - period_end_dt).total_seconds() / 86400.0

                    if days_passed < 7:
                        # Извлекаем метрики из загруженного файла
                        vol_med = data.get("volume", {}).get("median", 0.0)
                        doi_med = data.get("abs_doi", {}).get("median", 0.0)
                        dprice_med = data.get("abs_dprice", {}).get("median", 0.0)

                        p_start = data.get("period_start", "N/A")
                        p_end = data.get("period_end", "N/A")

                        print("================================================================================")
                        print(f"Period: {p_start} -> {p_end}")
                        print(
                            f"Volume Median: {vol_med:.1f} | dOI Median: {doi_med:.3f}% | dPrice Median: {dprice_med:.3f}%")
                        return
                    else:
                        print(f"⏳ [BASELINE] Файлу больше 7 дней ({days_passed:.1f} дней). Запускаем обновление...")
            except Exception as read_err:
                print(f"⚠️ [BASELINE] Ошибка чтения {BASELINE_FILE}: {read_err}. Запускаем перерасчет.")

        # 2. Если файла нет или он устарел — запускаем перерасчет
        print("🔄 [BASELINE] Расчет медианных метрик за 30 дней...")
        calculator = BaselineCalculator(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            history_days=30,
            timezone_offset=TIMEZONE_OFFSET,
            output_json=BASELINE_FILE
        )
        calculator.calculate_and_save()

    except Exception as e:
        print(f"❌ Error calculating baseline: {e}")
        traceback.print_exc()


def run_market_snapshot():
    # 1. Session Scanner Output
    try:
        scanner = TodaySessionScanner(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            timezone_offset=TIMEZONE_OFFSET,
            baseline_file=BASELINE_FILE
        )
        scanner.evaluate_today()
    except Exception as e:
        print(f"❌ Error in session scanner: {e}")
        traceback.print_exc()

    print("-" * 50)

    # 2. Level Detector Output
    try:
        detector = LevelDetector(
            symbol=SYMBOL,
            baseline_file=BASELINE_FILE,
            timezone_offset=TIMEZONE_OFFSET
        )
        detector.print_report()
    except Exception as e:
        print(f"❌ Error in level detector: {e}")
        traceback.print_exc()

def main():
    run_baseline()
    run_market_snapshot()

    printer = BinanceFuturesLivePrinter(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        timezone_offset=TIMEZONE_OFFSET
    )

    print_header("LIVE MARKET MONITOR ACTIVATED")

    last_baseline_update = time.time()
    last_printed_minute = -1

    while True:
        try:
            now_dt = datetime.now()
            current_minute = now_dt.minute

            # Получаем свечу каждую минуту для отслеживания закрытия часа
            active_candle_ms = printer.get_live_data_silent_or_check()

            # 1. Проверяем, не закрылся ли час
            if active_candle_ms:
                if printer.current_candle_open_ms is not None and active_candle_ms > printer.current_candle_open_ms:
                    closed_candle_ms = printer.current_candle_open_ms
                    # Вызываем печать итогов закрывшегося часа
                    printer.get_live_data(force_summary_for_closed=closed_candle_ms)

                printer.current_candle_open_ms = active_candle_ms

            # 2. Вывод лога раз в 10 минут (на 0, 10, 20, 30, 40, 50 минутах)
            if current_minute % 10 == 0 and current_minute != last_printed_minute:
                printer.get_live_data()
                last_printed_minute = current_minute

            # 3. Проверка недельного обновления
            current_time = time.time()
            if current_time - last_baseline_update >= BASELINE_UPDATE_INTERVAL:
                run_baseline()
                print_header("SCHEDULED WEEKLY SNAPSHOT UPDATE")
                run_market_snapshot()
                last_baseline_update = current_time

            time.sleep(15)  # Опрашиваем раз в 15 секунд для точности

        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            traceback.print_exc()
            time.sleep(15)
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Live monitor stopped by user.")