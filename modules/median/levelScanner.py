import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta


class LiquidityLevelScanner:
    def __init__(
            self,
            symbol: str = "BTCUSDT",
            timeframe: str = "4h",  # Для среднесрочных уровней лучше 4h или 1h
            days_back: int = 60,  # Глубина истории (60 дней)
            tolerance_pct: float = 0.4,  # Погрешность объединения близких уровней в 1 кластер (0.4%)
            timezone_offset: int = 5
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.limit = min(days_back * (24 // int(timeframe.replace('h', '')) if 'h' in timeframe else 24), 1000)
        self.tolerance_pct = tolerance_pct
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"

    def fetch_klines(self) -> pd.DataFrame:
        """ Загружает историю свечей для поиска Pivot Points """
        url = f"{self.base_url}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": self.timeframe, "limit": self.limit}
        res = requests.get(url, params=params).json()

        df = pd.DataFrame(res, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])

        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)

        offset_hours = timedelta(hours=self.timezone_offset)
        tz_info = timezone(offset_hours)

        df['time'] = (
            pd.to_datetime(df['open_time'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )
        return df

    def find_pivot_points(self, df: pd.DataFrame, window: int = 3) -> list:
        """
        Ищет локальные максимумы (Resistance) и минимумы (Support).
        window=3 означает, что экстремум выше/ниже 3 свечей слева и 3 свечей справа.
        """
        pivots = []
        for i in range(window, len(df) - window):
            high_range = df['high'].iloc[i - window: i + window + 1]
            low_range = df['low'].iloc[i - window: i + window + 1]

            current_high = df['high'].iloc[i]
            current_low = df['low'].iloc[i]

            # Swing High (Сопротивление)
            if current_high == high_range.max():
                pivots.append({
                    "price": current_high,
                    "type": "RESISTANCE",
                    "time": df['time'].iloc[i],
                    "volume": df['volume'].iloc[i],
                    "index": i
                })

            # Swing Low (Поддержка)
            if current_low == low_range.min():
                pivots.append({
                    "price": current_low,
                    "type": "SUPPORT",
                    "time": df['time'].iloc[i],
                    "volume": df['volume'].iloc[i],
                    "index": i
                })

        return pivots

    def cluster_and_score_levels(self, df: pd.DataFrame, pivots: list) -> pd.DataFrame:
        """
        Группирует близкие пивоты в единые зоны/уровни и рассчитывает Силу Уровня (Strength Score).
        """
        if not pivots:
            return pd.DataFrame()

        current_price = df['close'].iloc[-1]
        mean_volume = df['volume'].mean()

        # Сортируем пивоты по цене
        pivots_sorted = sorted(pivots, key=lambda x: x['price'])

        clusters = []
        current_cluster = [pivots_sorted[0]]

        for p in pivots_sorted[1:]:
            prev_price = current_cluster[-1]['price']
            # Если разница в цене меньше tolerance_pct %, объединяем в один уровень
            if abs(p['price'] - prev_price) / prev_price * 100 <= self.tolerance_pct:
                current_cluster.append(p)
            else:
                clusters.append(current_cluster)
                current_cluster = [p]
        clusters.append(current_cluster)

        processed_levels = []

        for cl in clusters:
            prices = [p['price'] for p in cl]
            level_price = float(np.mean(prices))
            touch_count = len(cl)

            # Определяем тип (Поддержка если ниже текущей цены, Сопротивление если выше)
            level_type = "RESISTANCE" if level_price > current_price else "SUPPORT"

            # МЕТРИКИ СИЛЫ ("БЕТОННОСТИ"):
            # 1. Количество касаний (до 40 баллов)
            score_touches = min(touch_count * 10, 40)

            # 2. Объем на касаниях (до 30 баллов)
            avg_cluster_vol = np.mean([p['volume'] for p in cl])
            vol_ratio = avg_cluster_vol / mean_volume
            score_volume = min(vol_ratio * 15, 30)

            # 3. Свежесть / Нецелостность (Unswept Status)
            # Проверяем, пробивала ли цена этот уровень после последнего пивота
            last_pivot_idx = max([p['index'] for p in cl])
            future_candles = df.iloc[last_pivot_idx + 1:]

            if level_type == "RESISTANCE":
                is_broken = (future_candles['high'] > level_price * 1.002).any()
            else:
                is_broken = (future_candles['low'] < level_price * 0.998).any()

            score_freshness = 30 if not is_broken else 5  # Если уровень не пробит, он цел и содержит стопы (+30 баллов)

            # Итоговый Score (0 - 100)
            total_score = round(score_touches + score_volume + score_freshness, 1)

            # Категория «бетонности»
            if total_score >= 70:
                strength_tag = "🧱 CONCRETE (Бетон)"
            elif total_score >= 45:
                strength_tag = "⚔️ STRONG (Сильный)"
            else:
                strength_tag = "🔹 WEAK (Слабый)"

            dist_pct = round(((level_price - current_price) / current_price) * 100, 2)

            processed_levels.append({
                "level_price": round(level_price, 2),
                "type": level_type,
                "distance_pct": dist_pct,
                "touches": touch_count,
                "score": total_score,
                "strength": strength_tag,
                "is_clean_unswept": not is_broken
            })

        df_levels = pd.DataFrame(processed_levels)
        # Фильтруем: берем ближайшие к текущей цене уровни
        df_levels = df_levels.sort_values(by="distance_pct", key=abs).reset_index(drop=True)
        return df_levels


if __name__ == "__main__":
    scanner = LiquidityLevelScanner(symbol="BTCUSDT", timeframe="4h", days_back=60, tolerance_pct=0.5)

    print("Загружаем данные и рассчитываем сильные уровни...")
    df_klines = scanner.fetch_klines()
    current_price = df_klines['close'].iloc[-1]

    pivots = scanner.find_pivot_points(df_klines, window=3)
    df_levels = scanner.cluster_and_score_levels(df_klines, pivots)

    print(f"\n===================================================================================")
    print(f" 🎯 КЛЮЧЕВЫЕ УРОВНИ ЛИКВИДНОСТИ ДЛЯ {scanner.symbol} (Текущая цена: {current_price})")
    print(f"===================================================================================\n")

    # Показываем 5 ближайших сопротивлений и 5 ближайших поддержек
    res_levels = df_levels[df_levels['type'] == 'RESISTANCE'].head(5)
    sup_levels = df_levels[df_levels['type'] == 'SUPPORT'].head(5)

    print("--- 🔴 СОПРОТИВЛЕНИЯ (RESISTANCE - Сверху) ---")
    for _, r in res_levels.iterrows():
        print(
            f"• Level: {r['level_price']:<8} | Дистанция: +{r['distance_pct']:<5}% | "
            f"Касаний: {r['touches']} | Score: {r['score']}/100 | {r['strength']}"
        )

    print("\n--- 🟢 ПОДДЕРЖКИ (SUPPORT - Снизу) ---")
    for _, s in sup_levels.iterrows():
        print(
            f"• Level: {s['level_price']:<8} | Дистанция: {s['distance_pct']:<5}% | "
            f"Касаний: {s['touches']} | Score: {s['score']}/100 | {s['strength']}"
        )