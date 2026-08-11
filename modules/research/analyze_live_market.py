import requests
import pandas as pd
import time
import json
import os
import traceback
from datetime import datetime, timezone, timedelta

class BinanceFuturesLivePrinter:
    def __init__(self, symbol: str = "BTCUSDT", timeframe: str = "1h", timezone_offset: int = 5):
        self.symbol = symbol
        self.timeframe = timeframe
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"
        
        # Так как файл лежит прямо в папке research, проверяем локальный путь
        self.json_filename = "baseline_metrics.json"
        self.vol_median = self._load_vol_median_from_json()

    def _load_vol_median_from_json(self) -> float:
        default_median = 1500.0
        
        if os.path.exists(self.json_filename):
            try:
                with open(self.json_filename, "r", encoding="utf-8") as f:
                    metrics = json.load(f)
                
                # Точечно забираем значение из твоей структуры
                if "volume" in metrics and "median" in metrics["volume"]:
                    found_median = float(metrics["volume"]["median"])
                    # print(f"📊 Базовая медиана объема успешно взята из JSON: {found_median}")
                    return found_median
                
                print("⚠️ Ключ ['volume']['median'] не найден в JSON.")
            except Exception as e:
                print(f"❌ Ошибка при чтении или парсинге JSON: {e}")
        else:
            print(f"⚠️ Файл {self.json_filename} не найден.")
            
        print(f" Используем дефолтное значение: {default_median}")
        return default_median
        default_median = 1500.0
        
        if os.path.exists(self.json_filename):
            try:
                with open(self.json_filename, "r", encoding="utf-8") as f:
                    metrics = json.load(f)
                
                # Выводим ключи в консоль, чтобы точно знать, что внутри файла
                print(f" debug: Доступные ключи в JSON: {list(metrics.keys())}")
                
                # Проверяем все возможные варианты названия ключа
                target_key = None
                for key in ["vol_median", "vol_median", "Volume", "vol"]:
                    if key in metrics:
                        target_key = key
                        break
                
                if target_key:
                    if isinstance(metrics[target_key], dict):
                        # Если это вложенный словарь (например, {"Volume": {"Median": 123}})
                        sub_dict = metrics[target_key]
                        for sub_key in ["Median", "median", "vol_median"]:
                            if sub_key in sub_dict:
                                found_median = float(sub_dict[sub_key])
                                print(f"📊 Медиана объема взята из [{target_key}][{sub_key}]: {found_median}")
                                return found_median
                    else:
                        # Если это плоский JSON (например, {"vol_median": 123})
                        found_median = float(metrics[target_key])
                        print(f"📊 Медиана объема взята из [{target_key}]: {found_median}")
                        return found_median

                print("⚠️ В JSON файле не найден подходящий ключ для медианы объема.")
            except Exception as e:
                print(f"❌ Ошибка при чтении или парсинге JSON: {e}")
        else:
            print(f"⚠️ Файл {self.json_filename} физически не найден в папке.")
            
        print(f" Используем дефолтное значение: {default_median}")
        return default_median

    def get_live_data(self):
        # 1. Запрос свечей
        klines_url = f"{self.base_url}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": self.timeframe, "limit": 2}
        
        try:
            res_klines = requests.get(klines_url, params=params).json()
            if not isinstance(res_klines, list) or len(res_klines) < 2:
                print("❌ Ошибка API Binance: Неверный формат свечей.")
                return
        except Exception as e:
            print(f"❌ Ошибка сети при запросе свечей: {e}")
            return

        # Парсим текущую свечу
        try:
            open_time_ms = res_klines[1][0]
            c_open = float(res_klines[1][1])
            c_close = float(res_klines[1][4])
            c_volume = float(res_klines[1][5])
            c_taker_volume = float(res_klines[1][9])
        except (IndexError, ValueError, TypeError) as e:
            print(f"❌ Ошибка парсинга данных свечи: {e}")
            return

        # Расчет времени
        offset_hours = timedelta(hours=self.timezone_offset)
        tz_info = timezone(offset_hours)
        candle_open_time = pd.to_datetime(open_time_ms, unit='ms', utc=True).tz_convert(tz_info).tz_localize(None)
        
        now_time = datetime.now()
        minutes_passed = int((now_time - candle_open_time).total_seconds() // 60)
        minutes_passed = max(1, min(minutes_passed, 60))

        # 2. Запрос текущего OI
        realtime_oi = 0.0
        try:
            oi_url = f"{self.base_url}/fapi/v1/openInterest"
            res_oi = requests.get(oi_url, params={"symbol": self.symbol}).json()
            if isinstance(res_oi, dict) and 'openInterest' in res_oi:
                realtime_oi = float(res_oi['openInterest'])
        except Exception:
            pass

        # 3. Запрос исторического OI
        last_closed_oi = 0.0
        try:
            oi_history_url = f"{self.base_url}/futures/data/openInterestHist"
            res_hist = requests.get(oi_history_url, params={"symbol": self.symbol, "period": self.timeframe, "limit": 2}).json()
            if isinstance(res_hist, list) and len(res_hist) > 0:
                last_closed_oi = float(res_hist[0]['sumOpenInterest'])
        except Exception:
            pass

        # Безопасный расчет метрик
        try:
            live_price_pct = ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0
            
            if realtime_oi > 0 and last_closed_oi > 0:
                live_oi_pct = ((realtime_oi - last_closed_oi) / last_closed_oi) * 100
            else:
                live_oi_pct = 0.0

            oi_speed = live_oi_pct / minutes_passed
            projected_volume = (c_volume / minutes_passed) * 60
            
            # Защита от деления на ноль или кривого вола
            base_med = self.vol_median if self.vol_median > 0 else 1500.0
            projected_vol_ratio = projected_volume / base_med
            
            taker_buy_pct = (c_taker_volume / c_volume * 100) if c_volume > 0 else 0.0
        except Exception as e:
            print(f"❌ Ошибка при математических расчетах: {e}")
            return

        # Безопасный вывод строки
        try:
            console_output = (
                f"[{now_time.strftime('%H:%M')} | {minutes_passed}m/60m] "
                f"BTC: {c_close:.1f} ({live_price_pct:+.2f}%) | "
                f"dOI: {live_oi_pct:+.2f}% (Spd: {oi_speed:+.4f}%/m) | "
                f"Vol: {c_volume:.0f} (Proj: {projected_vol_ratio:.2f}x Med) | "
                f"TakerBuy: {taker_buy_pct:.1f}%"
            )
            print(console_output, flush=True) # flush=True принудительно очищает буфер вывода
        except Exception as e:
            print(f"❌ Ошибка форматирования строки вывода: {e}")


if __name__ == "__main__":
    printer = BinanceFuturesLivePrinter(symbol="BTCUSDT", timeframe="1h", timezone_offset=5)
    print(f"🚀 Running Live Output Monitor for {printer.symbol} (Every 10 min)...", flush=True)
    
    while True:
        try:
            printer.get_live_data()
        except Exception as e:
            print("❌ Критическая ошибка в основном цикле:")
            traceback.print_exc()
        
        time.sleep(600)