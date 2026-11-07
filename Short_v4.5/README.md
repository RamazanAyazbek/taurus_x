# TAURUS SHORT v7.5 — S1

Windows: `py -m pip install -r requirements.txt`, затем `py main.py`.

Все параметры — в `config.py`. Исходная логика SHORT/TP/SL сохранена.

- `SUPPORT_FILTER_ENABLED = True` — запретить вход у/в S1 из Collector.
- `SUPPORT_NEAR_PCT = 0.35` — допустимая дистанция до верхней границы S1, %.
- `SUPPORT_COOLDOWN_MINUTES = 0/10/20/30` — пауза после запрета; по её окончании нужен новый сигнал и подтверждение, старый сигнал не исполняется.
- `SUPPORT_RECHECK_AT_ENTRY = True` — проверить ту же S1 ещё раз при фактическом моделируемом входе по Binance OPEN, используя лишь известные к подтверждению зоны.
- `ENTRY_PRICE_SOURCE = "binance_open"` и `ENTRY_DELAY_MINUTES = 3` — симулировать открытие по Binance 1m OPEN через 3 минуты после наблюдения подтверждения (примерно как решение Reactor); это не гарантированный MARKET fill.
- `ENTRY_PRICE_SOURCE = "collector"` — прежняя симуляция по цене Collector для сравнения; тогда `ENTRY_DELAY_MINUTES` не используется.

Вывод терминала компактный; полный отчёт .xlsx: `Summary`, `Trades`, `S1_Rejections`.

Для честной проверки эффекта S1 сравнивай режимы с **одинаковым** `ENTRY_PRICE_SOURCE` и `ENTRY_DELAY_MINUTES` и меняй только `SUPPORT_COOLDOWN_MINUTES` или `SUPPORT_FILTER_ENABLED`.

Особенности старой логики, которые **не меняли**: незавершённые позиции без 1m истории не входят в список сделок; комиссии и State Lock остаются как были. При входе по Binance OPEN первая минутная свеча проверяется на TP/SL; если уровни достигаются в одной минуте, приоритет у SL. Принято, что OPEN 1m совпадает с моментом исполнения. В реальном Reactor цена может отличаться из-за фактической задержки/спреда/проскальзывания.
