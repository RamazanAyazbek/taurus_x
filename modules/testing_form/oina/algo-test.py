# taurus_simulator.py

import re
import threading
from typing import Optional, Dict, Any, List


class RealtimeSimulator:
    def __init__(self, tp_pct: float = 1.5, sl_pct: float = 0.7, taker_fee: float = 0.05, maker_fee: float = 0.02):
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee

        self.position: Optional[Dict[str, Any]] = None
        self.trades: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

        # Универсальное регулярное выражение (поддерживает старый и новый формат логов)
        self.log_pattern = re.compile(
            r'(?:(?P<log_date>\d{4}-\d{2}-\d{2})\s+)?'
            r'\[(?P<timestamp>[^\]]+)\]\s+'
            r'BTC:\s+(?P<price>[\d\.]+)\s+\((?P<dPrice_str>[^)]+)\).*?'
            r'dOI:\s+(?P<dOI_str>[%\d\.\+\-]+).*?'
            r'Vol:\s+(?P<vol>\d+).*?'
            r'TakerBuy:\s+(?P<taker_buy>[\d\.]+)%'
        )

    def parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Разбирает одну строку лога taurus_x."""
        match = self.log_pattern.search(line)
        if not match:
            return None

        try:
            price = float(match.group('price'))
            d_price_val = float(match.group('dPrice_str').replace('%', '').replace('+', ''))
            d_oi_val = float(match.group('dOI_str').replace('%', '').replace('+', ''))
            vol = float(match.group('vol'))
            taker_buy = float(match.group('taker_buy'))

            # Извлекаем чистый численный таймстемп (например, "2026-09-04 09:30")
            ts = match.group('timestamp').split(' | ')[0].strip()

            in_zone = line.split('🎯 IN:')[1].strip() if '🎯 IN:' in line else 'NONE'

            return {
                'timestamp': ts,
                'price': price,
                'dPrice': d_price_val,
                'dOI': d_oi_val,
                'volume': vol,
                'taker_buy': taker_buy,
                'in_zone': in_zone
            }
        except ValueError:
            return None

    def process_line(self, line: str):
        """Принимает новую строку из лог-стрима и обновляет состояние симулятора."""
        data = self.parse_log_line(line)
        if not data:
            return

        with self._lock:
            price = data['price']

            # 1. Проверка TP / SL для открытой позиции
            if self.position:
                pos = self.position
                pos_type = pos['type']

                is_tp = (pos_type == 'LONG' and price >= pos['tp_price']) or \
                        (pos_type == 'SHORT' and price <= pos['tp_price'])

                is_sl = (pos_type == 'LONG' and price <= pos['sl_price']) or \
                        (pos_type == 'SHORT' and price >= pos['sl_price'])

                if is_tp or is_sl:
                    reason = 'Take-Profit' if is_tp else 'Stop-Loss'
                    exit_price = pos['tp_price'] if is_tp else pos['sl_price']

                    if pos_type == 'LONG':
                        price_change_pct = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100
                    else:
                        price_change_pct = ((pos['entry_price'] - exit_price) / pos['entry_price']) * 100

                    exit_offset_usd = round(abs(exit_price - pos['entry_price']), 1)

                    exit_fee = self.maker_fee if is_tp else self.taker_fee
                    total_fee_pct = self.taker_fee + exit_fee
                    net_pnl_pct = round(price_change_pct - total_fee_pct, 2)

                    trade_record = {
                        'entry_time': pos['entry_time'],
                        'exit_time': data['timestamp'],
                        'type': pos_type,
                        'entry_price': pos['entry_price'],
                        'exit_price': exit_price,
                        'exit_offset_usd': exit_offset_usd,
                        'tp_price': pos['tp_price'],
                        'sl_price': pos['sl_price'],
                        'pnl_pct': round(price_change_pct, 2),
                        'net_pnl_pct': net_pnl_pct,
                        'result': 'WIN' if is_tp else 'LOSS',
                        'exit_reason': reason,
                        'entry_dOI': pos['entry_dOI'],
                        'entry_dPrice': pos['entry_dPrice'],
                        'entry_volume': pos['entry_volume'],
                        'entry_taker_buy': pos['entry_taker_buy'],
                        'entry_zone': pos['entry_zone']
                    }

                    self.trades.append(trade_record)
                    self.position = None

            # 2. Логика открытия позиции (в точности из taurus_algorithm.py)
            if not self.position:
                d_price = data['dPrice']
                d_oi = data['dOI']
                vol = data['volume']
                taker_buy = data['taker_buy']
                zone = str(data['in_zone'])

                # LONG Сигнал
                if d_price > 0.3 and taker_buy > 55.0:
                    if not (d_oi < -0.7 and vol < 20000) and (taker_buy <= 66.0) and (vol >= 7200):
                        tp_price = round(price * (1 + self.tp_pct / 100), 1)
                        sl_price = round(price * (1 - self.sl_pct / 100), 1)
                        self._open_pos('LONG', price, data, tp_price, sl_price)

                # SHORT Сигнал
                elif d_price < -0.6 and taker_buy < 38.0:
                    if 'S1' not in zone and 'S2' not in zone:
                        tp_price = round(price * (1 - self.tp_pct / 100), 1)
                        sl_price = round(price * (1 + self.sl_pct / 100), 1)
                        self._open_pos('SHORT', price, data, tp_price, sl_price)

    def _open_pos(self, pos_type: str, price: float, data: Dict[str, Any], tp_price: float, sl_price: float):
        self.position = {
            'type': pos_type,
            'entry_price': price,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'entry_time': data['timestamp'],
            'entry_dOI': data['dOI'],
            'entry_dPrice': data['dPrice'],
            'entry_volume': data['volume'],
            'entry_taker_buy': data['taker_buy'],
            'entry_zone': data['in_zone']
        }

    def get_state(self) -> Dict[str, Any]:
        """Возвращает текущую активную позицию и список всех совершенных сделок."""
        with self._lock:
            return {
                "active_position": self.position,
                "completed_trades": self.trades,
                "total_trades": len(self.trades)
            }

if __name__ == "__main__":
    log_file = "taurus_x_container.log"
    try:
        df_logs = parse_taurus_log(log_file)
        tester = TaurusAnalyticalBacktester(tp_pct=1.5, sl_pct=0.7)
        tester.run(df_logs)
        tester.export_analysis()
    except FileNotFoundError:
        print(f"Файл {log_file} не найден.")