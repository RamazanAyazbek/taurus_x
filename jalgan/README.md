# Taurus Backtest Modular

Запуск:

```bash
python main.py
```

Основные параметры находятся только в `config.py`.

Модули:

- `config.py` — параметры и переключатели
- `log_parser.py` — парсинг Taurus log
- `market_data.py` — загрузка Binance 1m klines
- `oi_features.py` — OI features
- `signal_logic.py` — фильтры и V5 signal
- `exit_logic.py` — TP / SL / TIMEOUT
- `movement_profile.py` — независимый movement profile
- `backtester.py` — основной движок
- `reporter.py` — статистика и CSV
- `main.py` — запуск

## Переключатели

В `config.py` можно отключать независимые блоки:

```python
ENABLE_MOVEMENT_PROFILE = False
ENABLE_OI_FEATURES = False
ENABLE_STATE_LOCK = False
ENABLE_PREVIOUS_2H_4H = False
ENABLE_PREVIOUS_30M = False
ENABLE_FEES = False
```

Отключенный блок не должен требовать свои данные для работы остального бэктеста.

TP / SL / BE / TIMEOUT также задаются только в `config.py`.

`BE_PCT` сохранен как параметр, но фактическая BE-механика не добавлялась, поскольку в исходном коде она не участвовала в расчете сделки.
