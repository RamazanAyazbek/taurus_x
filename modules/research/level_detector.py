import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime


class LevelDetector:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        baseline_file: str = "baseline_metrics.json",
        timezone_offset: int = 5
    ):
        self.symbol = symbol
        self.baseline_file = baseline_file
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"
        self.dprice_median = self.load_baseline_volatility()

    def load_baseline_volatility(self) -> float:
        if not os.path.exists(self.baseline_file):
            return 0.2
        with open(self.baseline_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("abs_dprice", {}).get("median", 0.2)

    def fetch_candles(self, interval: str, limit: int) -> pd.DataFrame:
        url = f"{self.base_url}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": interval, "limit": limit}
        res = requests.get(url, params=params).json()
        df = pd.DataFrame(res, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        return df

    def find_raw_levels(self, df: pd.DataFrame, window: int = 3) -> list:
        levels = []
        for i in range(window, len(df) - window):
            if df['low'].iloc[i] == df['low'].iloc[i - window:i + window + 1].min():
                levels.append({"type": "SUPPORT", "price": df['low'].iloc[i]})
            if df['high'].iloc[i] == df['high'].iloc[i - window:i + window + 1].max():
                levels.append({"type": "RESISTANCE", "price": df['high'].iloc[i]})
        return levels

    def cluster_levels_into_zones(self, raw_levels: list, current_price: float, timeframe_weight: int) -> list:
        if not raw_levels:
            return []

        zone_half_width = current_price * (self.dprice_median / 100)
        raw_levels = sorted(raw_levels, key=lambda x: x['price'])
        
        zones = []
        current_zone = []

        for lvl in raw_levels:
            if not current_zone:
                current_zone.append(lvl)
            else:
                prev_price = current_zone[-1]['price']
                if lvl['price'] - prev_price <= zone_half_width * 1.5:
                    current_zone.append(lvl)
                else:
                    zones.append(current_zone)
                    current_zone = [lvl]
        if current_zone:
            zones.append(current_zone)

        formatted_zones = []
        for zone in zones:
            prices = [x['price'] for x in zone]
            mean_price = np.mean(prices)
            floor = mean_price - zone_half_width
            ceil = mean_price + zone_half_width
            
            touches = len(zone)
            # Математический расчёт силы: контакты + вес таймфрейма (D1 тяжелее, чем H1)
            score = (touches * 2) + timeframe_weight

            formatted_zones.append({
                "core_price": round(mean_price, 1),
                "floor": round(floor, 1),
                "ceil": round(ceil, 1),
                "touches": touches,
                "score": score
            })

        return formatted_zones

    def get_tracked_zones(self) -> dict:
        df_d1 = self.fetch_candles(interval="1d", limit=30)
        df_h1 = self.fetch_candles(interval="1h", limit=96)
        current_price = df_h1['close'].iloc[-1]

        raw_d1 = self.find_raw_levels(df_d1, window=2)
        raw_h1 = self.find_raw_levels(df_h1, window=4)

        # Передаем вес: для D1 = 5 базовых очков силы, для H1 = 1 очко
        zones_d1 = self.cluster_levels_into_zones(raw_d1, current_price, timeframe_weight=5)
        zones_h1 = self.cluster_levels_into_zones(raw_h1, current_price, timeframe_weight=1)

        reach_limit = 0.05 
        
        all_zones = []
        for z in zones_d1:
            if abs(z['core_price'] - current_price) / current_price <= reach_limit:
                z['tf'] = 'D1'
                all_zones.append(z)
        for z in zones_h1:
            if abs(z['core_price'] - current_price) / current_price <= reach_limit:
                z['tf'] = 'H1'
                all_zones.append(z)

        return {
            "current_price": current_price,
            "zones": all_zones
        }

    def print_report(self):
        data = self.get_tracked_zones()
        cp = data['current_price']
        zones = data['zones']

        # Разделяем на поддержки и сопротивления
        supports = [z for z in zones if z['ceil'] < cp]
        resistances = [z for z in zones if z['floor'] > cp]

        # Сортируем: поддержки по возрастанию цены, сопротивления по возрастанию цены
        supports = sorted(supports, key=lambda x: x['core_price'])
        resistances = sorted(resistances, key=lambda x: x['core_price'])

        # --- Расчет наименьшего сопротивления (в пределах 1.5% хода цены) ---
        scan_range = cp * 0.015
        near_supps = [z for z in supports if (cp - z['core_price']) <= scan_range]
        near_resis = [z for z in resistances if (z['core_price'] - cp) <= scan_range]

        score_down = sum([z['score'] for z in near_supps])
        score_up = sum([z['score'] for z in near_resis])

        dist_to_supp = (cp - supports[-1]['core_price']) if supports else scan_range
        dist_to_res = (resistances[0]['core_price'] - cp) if resistances else scan_range

        # Вычисление вектора
        if score_up == score_down:
            path_bias = "NEUTRAL (Сопротивление симметрично)"
            ratio = 1.0
        elif score_up > score_down:
            ratio = score_up / max(1, score_down)
            path_bias = f"DOWNWARD (Вниз идти легче в {ratio:.1f}x раз, сверху сильные блоки)"
        else:
            ratio = score_down / max(1, score_up)
            path_bias = f"UPWARD (Вверх идти легче в {ratio:.1f}x раз, снизу сильные блоки)"

        # --- ВЫВОД В ТЕРМИНАЛ ---
        print("=" * 90)
        print(f"📊 TAURUS MARKET MAP ({self.symbol}) | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Baseline dynamic width: ±{self.dprice_median}%")
        print("=" * 90)

        # 1. Вывод сопротивлений (вверху шкалы, по возрастанию)
        print("   ▲ [RESISTANCE ZONES]")
        for z in reversed(resistances):  # Выводим инверсировано, чтобы самые высокие были в самом верху терминала
            print(f"   | [{z['tf']}] Zone: {z['floor']} - {z['ceil']} | Core: {z['core_price']:7.1f} | Touches: {z['touches']:2d} | Score: {z['score']:2d}")
        
        # 2. Вывод Текущей цены (Разделитель)
        print(f" ══♦══ CURRENT PRICE: {cp} ══♦══")

        # 3. Вывод поддержек (внизу шкалы, по убыванию к полу)
        for z in reversed(supports):
            print(f"   | [{z['tf']}] Zone: {z['floor']} - {z['ceil']} | Core: {z['core_price']:7.1f} | Touches: {z['touches']:2d} | Score: {z['score']:2d}")
        print("   ▼ [SUPPORT ZONES]")

        print("-" * 90)
        print("💡 LEFEVRE PATH OF LEAST RESISTANCE (In the intraday range 1.5%):")
        print(f"   • (Res-Score): {score_up} (closest {dist_to_res:.1f} pts)")
        print(f"   • (Sup-Score): {score_down} (closest {dist_to_supp:.1f} pts)")
        print(f"   • LEFEVRE VECTOR   : {path_bias}")
        print("=" * 90 + "\n")


if __name__ == "__main__":
    detector = LevelDetector(
        symbol="BTCUSDT",
        baseline_file="baseline_metrics.json",
        timezone_offset=5
    )
    detector.print_report()