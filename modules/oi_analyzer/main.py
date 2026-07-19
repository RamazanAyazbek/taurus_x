import os
import sys
import time
import queue
import logging
import threading
import traceback
from datetime import datetime, timezone, timedelta
from core.binance_client import BinanceFuturesClient
from modules.oi_analyzer.history_manager import HistoryManager
from .raw_collector01 import run_collector
from .strategy_processor02 import process_strategy
from .research_tracker03 import check_and_track

try:
    from config import POLLING_INTERVAL
except ImportError:
    POLLING_INTERVAL = 900

MAIN_LOG_PATH = "storage/oi/logs/oi_analyzer.log"
os.makedirs(os.path.dirname(MAIN_LOG_PATH), exist_ok=True)

logger = logging.getLogger("oi_analyzer")
logger.setLevel(logging.INFO)

# Форматтер для главного лог-файла в GMT+5
class GMT5Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=timezone(timedelta(hours=5)))
        return dt.strftime(datefmt if datefmt else "%Y-%m-%d %H:%M:%S GMT+5")

file_handler = logging.FileHandler(MAIN_LOG_PATH, encoding="utf-8")
file_handler.setFormatter(GMT5Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
logger.addHandler(file_handler)


class OpenInterestAnalyzerModule:
    def __init__(self, main_queue: queue.Queue):
        self.main_queue = main_queue
        self.client = BinanceFuturesClient()
        self.is_running = False

    def start_loop(self):
        self.is_running = True
        logger.info("Модуль Open Interest успешно инициализирован и запущен.")

        # Синхронизация 30 дней истории
        HistoryManager.sync_history(self.client)

        while self.is_running:
            try:
                # Спам-строка [OI] Проверка рынка... полностью удалена из вывода!
                raw_data = run_collector(self.client)
                analysis_res = process_strategy(raw_data, self.main_queue)
                check_and_track(analysis_res, self.client)

                time.sleep(POLLING_INTERVAL)

            except Exception as e:
                logger.error(f"Критический сбой в цикле oi_analyzer: {e}")
                with open(MAIN_LOG_PATH, "a", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
                time.sleep(60)

def start_module_in_thread(main_queue: queue.Queue) -> threading.Thread:
    analyzer = OpenInterestAnalyzerModule(main_queue)
    t = threading.Thread(target=analyzer.start_loop, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    test_queue = queue.Queue()
    analyzer = OpenInterestAnalyzerModule(test_queue)
    try:
        analyzer.start_loop()
    except KeyboardInterrupt:
        logger.info("Модуль остановлен пользователем.")