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
        
        self.json_filename = "baseline_metrics.json"
        self.vol_median = self._load_vol_median_from_json()
        
        # Храним ID текущей свечи, чтобы поймать момент, когда час закроется
        self.current_candle_open_ms = None

    def _load_vol_median_from_json(self) -> float:
        default_median = 1500.0
        if os.path.exists(self.json_filename):
            try:
                with open(self.json_filename, "r", encoding="utf-8") as f:
                    metrics = json.load(f)
                
                # Точечно забираем значение из структуры
                if "volume" in metrics and "median" in metrics["volume"]:
                    return float(metrics["volume"]["median"])
                
                # Ищем альтернативные ключи
                for key in ["vol_median", "Volume", "vol"]:
                    if key in metrics:
                        if isinstance(metrics[key], dict):
                            for sub_key in ["Median", "median", "vol_median"]:
                                if sub_key in metrics[key]:
                                    return float(metrics[key][sub_key])
                        else:
                            return float(metrics[key])
            except Exception as e:
                print(f"❌ Ошибка при чтении или парсинге JSON: {e}")
        return default_median

    def get_live_data(self, force_summary_for_closed=None):
        """
        force_summary_for_closed: передаем сюда прошлую свечу, если зафиксировали закрытие часа
        """
        klines_url = f"{self.base_url}/fapi/v1/klines"
        
        # Если нужно вывести итог закрытого часа, смотрим чуть глубже назад (limit: 3)
        params = {"symbol": self.symbol, "interval": self.timeframe, "limit": 3}
        
        try:
            res_klines = requests.get(klines_url, params=params).json()
            if not isinstance(res_klines, list) or len(res_klines) < 2:
                print("❌ Ошибка API Binance: Неверный формат свечей.")
                return None
        except Exception as e:
            print(f"❌ Ошибка сети при запросе свечей: {e}")
            return None

        # --- ЛОГИКА ИТОГОВ ЗАКРЫТОГО ЧАСА ---
        if force_summary_for_closed:
            # Ищем в истории свечу, которая только что закрылась
            closed_candle = None
            for k in res_klines:
                if k[0] == force_summary_for_closed:
                    closed_candle = k
                    break
            
            if closed_candle:
                self._print_hourly_summary(closed_candle)
            return None

        # --- ОБЫЧНЫЙ ТЕКУЩИЙ МОНИТОРИНГ ---
        active_candle = res_klines[-1] # Последняя (текущая) свеча
        open_time_ms = active_candle[0]
        
        try:
            c_open = float(active_candle[1])
            c_close = float(active_candle[4])
            c_volume = float(active_candle[5])
            c_taker_volume = float(active_candle[9])
        except (IndexError, ValueError, TypeError) as e:
            print(f"❌ Ошибка парсинга данных свечи: {e}")
            return None

        # Расчет времени
        candle_open_time_utc = pd.to_datetime(open_time_ms, unit='ms', utc=True)
        now_time_utc = datetime.now(timezone.utc)
        
        minutes_passed = int((now_time_utc - candle_open_time_utc).total_seconds() // 60)
        minutes_passed = max(1, min(minutes_passed, 60))
        local_output_time = now_time_utc + timedelta(hours=self.timezone_offset)

        # Запросы OI
        realtime_oi = 0.0
        try:
            res_oi = requests.get(f"{self.base_url}/fapi/v1/openInterest", params={"symbol": self.symbol}).json()
            if isinstance(res_oi, dict) and 'openInterest' in res_oi:
                realtime_oi = float(res_oi['openInterest'])
        except Exception: pass

        last_closed_oi = 0.0
        try:
            res_hist = requests.get(f"{self.base_url}/futures/data/openInterestHist", params={"symbol": self.symbol, "period": self.timeframe, "limit": 2}).json()
            if isinstance(res_hist, list) and len(res_hist) > 0:
                last_closed_oi = float(res_hist[-1]['sumOpenInterest'])
        except Exception: pass

        # Математика
        try:
            live_price_pct = ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0
            live_oi_pct = ((realtime_oi - last_closed_oi) / last_closed_oi) * 100 if (realtime_oi > 0 and last_closed_oi > 0) else 0.0
            oi_speed = live_oi_pct / minutes_passed
            
            projected_volume = (c_volume / minutes_passed) * 60
            base_med = self.vol_median if self.vol_median > 0 else 1500.0
            projected_vol_ratio = projected_volume / base_med
            
            taker_buy_pct = (c_taker_volume / c_volume * 100) if c_volume > 0 else 0.0
        except Exception as e:
            print(f"❌ Ошибка при математических расчетах: {e}")
            return open_time_ms

        # Вывод строки
        try:
            console_output = (
                f"[{local_output_time.strftime('%H:%M')} | {minutes_passed}m/60m] "
                f"BTC: {c_close:.1f} ({live_price_pct:+.2f}%) | "
                f"dOI: {live_oi_pct:+.2f}% (Spd: {oi_speed:+.4f}%/m) | "
                f"Vol: {c_volume:.0f} (Proj: {projected_vol_ratio:.2f}x Med) | "
                f"TakerBuy: {taker_buy_pct:.1f}%"
            )
            print(console_output, flush=True)
        except Exception as e:
            print(f"❌ Ошибка форматирования строки вывода: {e}")

        return open_time_ms

    def _print_hourly_summary(self, candle):
        """Метод для красивого вывода результатов закрывшегося часа"""
        try:
            open_time_ms = candle[0]
            c_open = float(candle[1])
            c_high = float(candle[2])
            c_low = float(candle[3])
            c_close = float(candle[4])
            c_volume = float(candle[5])
            
            # Определяем характер часа
            price_change_pct = ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0
            
            if c_close > c_open:
                status = "🟢 БЫЧИЙ (BULLISH)"
            elif c_close < c_open:
                status = "🔴 МЕДВЕЖИЙ (BEARISH)"
            else:
                status = "⚪️ НЕЙТРАЛЬНЫЙ (DOJI)"
                
            # Переводим время открытия закрывшегося часа в локальное для отчета
            open_time_local = pd.to_datetime(open_time_ms, unit='ms', utc=True) + timedelta(hours=self.timezone_offset)
            
            print("\n" + "="*70)
            print(f"⏰ ИТОГИ ЗАКРЫТОГО ЧАСА (Свеча от {open_time_local.strftime('%Y-%m-%d %H:%M')})")
            print(f"📊 Статус: {status}")
            print(f"📈 Изменение цены: {price_change_pct:+.2f}% (Open: {c_open:.1f} -> Close: {c_close:.1f})")
            print(f"🔍 Спред часа: High: {c_high:.1f} | Low: {c_low:.1f}")
            print(f"💎 Итоговый Объем: {c_volume:.0f} (Медиана: {self.vol_median:.0f})")
            print("="*70 + "\n", flush=True)
            
        except Exception as e:
            print(f"❌ Ошибка генерации отчета закрытия часа: {e}")


if __name__ == "__main__":
    printer = BinanceFuturesLivePrinter(symbol="BTCUSDT", timeframe="1h", timezone_offset=5)
    
    # Инициализируем стартовое время
    now = datetime.now(timezone.utc) + timedelta(hours=printer.timezone_offset)
    print("======================================================================")
    print(f"🔷 LIVE MARKET MONITOR ACTIVATED (10M INTERVAL) | {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("======================================================================")
    
    last_print_time = 0  # Таймер для 10-минутного шага логов

    while True:
        try:
            current_timestamp = time.time()
            
            # Запрашиваем состояние рынка
            active_candle_ms = printer.get_live_data()
            
            if active_candle_ms:
                # Если скрипт переключился на новую свечу, значит предыдущий час ЗАВЕРШИЛСЯ
                if printer.current_candle_open_ms is not None and active_candle_ms > printer.current_candle_open_ms:
                    closed_candle_ms = printer.current_candle_open_ms
                    # Запускаем экстренный сбор данных по только что закрытому часу
                    printer.get_live_data(force_summary_for_closed=closed_candle_ms)
                
                # Обновляем ID текущей свечи
                printer.current_candle_open_ms = active_candle_ms

            # Условие для принтов раз в 10 минут (или на 1-й минуте часа для точности)
            # Засыпаем на 60 секунд, чтобы проверять каждую минуту и не пропустить закрытие
            time.sleep(60)
            
        except Exception as e:
            print("❌ Критическая ошибка в основном цикле:")
            traceback.print_exc()
            time.sleep(60)