import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests


class LevelDetector:

  def __init__(
      self,
      symbol: str = 'BTCUSDT',
      baseline_file: str = 'baseline_metrics.json',
      timezone_offset: int = 5,
  ):
    self.symbol = symbol
    self.baseline_file = baseline_file
    self.timezone_offset = timezone_offset
    self.base_url = 'https://fapi.binance.com'
    self.dprice_median = self.load_baseline_volatility()

  def load_baseline_volatility(self) -> float:
    if not os.path.exists(self.baseline_file):
      return 0.2
    with open(self.baseline_file, 'r', encoding='utf-8') as f:
      data = json.load(f)
      return data.get('abs_dprice', {}).get('median', 0.2)

  def fetch_candles(self, interval: str, limit: int) -> pd.DataFrame:
    url = f'{self.base_url}/fapi/v1/klines'
    params = {'symbol': self.symbol, 'interval': interval, 'limit': limit}
    res = requests.get(url, params=params).json()
    df = pd.DataFrame(
        res,
        columns=[
            'open_time',
            'open',
            'high',
            'low',
            'close',
            'volume',
            'close_time',
            'quote_volume',
            'trades',
            'taker_buy_volume',
            'taker_buy_quote_volume',
            'ignore',
        ],
    )
    df[['open', 'high', 'low', 'close', 'volume']] = df[
        ['open', 'high', 'low', 'close', 'volume']
    ].astype(float)
    return df

  def find_raw_levels(self, df: pd.DataFrame, window: int = 5) -> list:
    """Увеличен дефолтный window для отсечения микро-колебаний."""
    levels = []
    for i in range(window, len(df) - window):
      if df['low'].iloc[i] == df['low'].iloc[i - window : i + window + 1].min():
        levels.append({
            'type': 'SUPPORT',
            'price': df['low'].iloc[i],
            'time': df['open_time'].iloc[i],
        })
      if (
          df['high'].iloc[i]
          == df['high'].iloc[i - window : i + window + 1].max()
      ):
        levels.append({
            'type': 'RESISTANCE',
            'price': df['high'].iloc[i],
            'time': df['open_time'].iloc[i],
        })
    return levels

  def merge_and_cluster_all_levels(
      self, raw_levels: list, current_price: float, min_score: int = 5
  ) -> list:
    """Сквозная кластеризация уровней со всех TF и фильтрация слабого шума."""
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
      mean_price = float(np.mean(prices))
      floor = mean_price - zone_half_width
      ceil = mean_price + zone_half_width

      touches = len(zone)
      # Подсчет суммарного веса с учетом таймфреймов
      score = sum([x['weight'] for x in zone]) + (touches * 2)

      # Определяем доминирующий TF для отображения
      tfs = [x['tf'] for x in zone]
      primary_tf = 'D1' if 'D1' in tfs else 'H1'

      # Фильтруем слишком слабые зоны (шум)
      if score >= min_score:
        formatted_zones.append({
            'core_price': round(mean_price, 1),
            'floor': round(floor, 1),
            'ceil': round(ceil, 1),
            'touches': touches,
            'score': score,
            'tf': primary_tf,
        })

    return formatted_zones

  def get_tracked_zones(self, min_score: int = 5) -> dict:
    df_d1 = self.fetch_candles(interval='1d', limit=30)
    df_h1 = self.fetch_candles(interval='1h', limit=96)
    current_price = df_h1['close'].iloc[-1]

    # Увеличили window: для D1 = 3, для H1 = 5
    raw_d1 = self.find_raw_levels(df_d1, window=3)
    raw_h1 = self.find_raw_levels(df_h1, window=5)

    # Добавляем метки TF и вес
    all_raw = []
    for r in raw_d1:
      r['tf'] = 'D1'
      r['weight'] = 5
      all_raw.append(r)

    for r in raw_h1:
      r['tf'] = 'H1'
      r['weight'] = 1
      all_raw.append(r)

    # Общая кластеризация
    zones = self.merge_and_cluster_all_levels(
        all_raw, current_price, min_score=min_score
    )

    reach_limit = 0.05
    filtered_zones = [
        z
        for z in zones
        if abs(z['core_price'] - current_price) / current_price <= reach_limit
    ]

    return {'current_price': current_price, 'zones': filtered_zones}

  def print_report(self):
    data = self.get_tracked_zones(min_score=5)
    cp = data['current_price']
    zones = data['zones']

    supports = [z for z in zones if z['ceil'] < cp]
    resistances = [z for z in zones if z['floor'] > cp]

    supports = sorted(supports, key=lambda x: x['core_price'])
    resistances = sorted(resistances, key=lambda x: x['core_price'])

    scan_range = cp * 0.015
    near_supps = [z for z in supports if (cp - z['core_price']) <= scan_range]
    near_resis = [z for z in resistances if (z['core_price'] - cp) <= scan_range]

    score_down = sum([z['score'] for z in near_supps])
    score_up = sum([z['score'] for z in near_resis])

    dist_to_supp = (
        (cp - supports[-1]['core_price']) if supports else scan_range
    )
    dist_to_res = (
        (resistances[0]['core_price'] - cp) if resistances else scan_range
    )

    if score_up == score_down:
      path_bias = 'NEUTRAL (Сопротивление симметрично)'
    elif score_up > score_down:
      ratio = score_up / max(1, score_down)
      path_bias = (
          f'DOWNWARD (Вниз идти легче в {ratio:.1f}x раз, сверху сильные блоки)'
      )
    else:
      ratio = score_down / max(1, score_up)
      path_bias = (
          f'UPWARD (Вверх идти легче в {ratio:.1f}x раз, снизу сильные блоки)'
      )

    print('=' * 90)
    print(
        f"📊 TAURUS MARKET MAP ({self.symbol}) |"
        f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print(f'🎯 Baseline dynamic width: ±{self.dprice_median}%')
    print('=' * 90)

    print('   ▲ [RESISTANCE ZONES]')
    for z in reversed(resistances):
      print(
          f"   | [{z['tf']}] Zone: {z['floor']} - {z['ceil']} | Core:"
          f" {z['core_price']:7.1f} | Touches: {z['touches']:2d} | Score:"
          f' {z['score']:2d}'
      )

    print(f' ══♦══ CURRENT PRICE: {cp} ══♦══')

    for z in reversed(supports):
      print(
          f"   | [{z['tf']}] Zone: {z['floor']} - {z['ceil']} | Core:"
          f" {z['core_price']:7.1f} | Touches: {z['touches']:2d} | Score:"
          f' {z['score']:2d}'
      )
    print('   ▼ [SUPPORT ZONES]')

    print('-' * 90)
    print('💡 LEFEVRE PATH OF LEAST RESISTANCE (In the intraday range 1.5%):')
    print(f'   • (Res-Score): {score_up} (closest {dist_to_res:.1f} pts)')
    print(f'   • (Sup-Score): {score_down} (closest {dist_to_supp:.1f} pts)')
    print(f'   • LEFEVRE VECTOR   : {path_bias}')
    print('=' * 90 + '\n')


if __name__ == '__main__':
  detector = LevelDetector(
      symbol='BTCUSDT', baseline_file='baseline_metrics.json', timezone_offset=5
  )
  detector.print_report()