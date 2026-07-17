# Trading System — scheletro infrastrutturale

Architettura event-driven: `DataFeed → Strategy → RiskManager → Broker → Portfolio`.
Lo stesso `Engine` (core/engine.py) gira identico in backtest, paper trading e live:
cambiano solo le implementazioni concrete di `DataFeed` e `Broker` che gli vengono
passate. Questo evita il problema più comune (logica diversa tra backtest e live che
diverge nel tempo).

## Struttura

```
core/        events.py (i messaggi che circolano), engine.py (il loop), portfolio.py
strategies/  base.py (interfaccia Strategy), ema_cross.py (implementazione di esempio)
risk/        manager.py (trasforma segnali in ordini dimensionati)
broker/      base.py (interfaccia), backtest_broker.py (simulato), ccxt_broker.py (paper/live)
data/        feed.py (CSV per backtest, ccxt polling per paper/live)
backtest/    run_backtest.py
live/        run_live.py (paper trading e live trading, stesso script)
```

## 1. Backtest

```bash
pip install -r requirements.txt
python -m data.generate_sample_data   # genera dati sintetici di prova
python -m backtest.run_backtest
```

Per usare dati reali al posto di quelli sintetici: basta creare un CSV con colonne
`timestamp,open,high,low,close,volume` (es. scaricato via `ccxt.fetch_ohlcv` e salvato
con pandas) e passarlo a `CSVDataFeed`.

## 2. Paper trading (automatico, consultabile mentre gira)

Usa il testnet dell'exchange (es. Binance Testnet: le chiavi si generano su
testnet.binance.vision, sono separate da quelle reali e non toccano soldi veri).

```bash
export BROKER_API_KEY=...
export BROKER_API_SECRET=...
pip install ccxt
python -m live.run_live --mode paper --symbol BTC/USDT --timeframe 1h
```

Lo script gira in loop continuo. Mentre gira, in un altro terminale (o dal browser):

```bash
curl http://localhost:8765/status
```

restituisce JSON con equity corrente, ultimo prezzo, numero di fill — niente bisogno
di leggere i log grezzi.

## 2bis. Journal (papertrading "su carta", nessun broker richiesto)

Modalità pensata per validare TP/SL e win rate senza integrare nessun broker:
apre trade virtuali quando la strategia genera un segnale e li chiude da solo
quando il prezzo tocca take-profit o stop-loss, usando solo dati pubblici di
mercato (nessuna API key, nessun account).

Backtest (su dati storici, per un riscontro immediato):
```bash
python -m journal.run_journal_backtest
```

Live (monitoraggio continuo su dati reali, nessuna esecuzione di ordini):
```bash
pip install ccxt
python -m journal.run_journal_live --symbol BTC/USDT --timeframe 1h --sl-pct 0.02 --tp-pct 0.04
```

Stato/win rate consultabili mentre gira:
```bash
curl http://localhost:8766/status
```

Limite da tenere presente: se in una singola barra vengono toccati sia TP che
SL, il broker assume conservativamente che lo SL sia stato colpito per primo
(non è possibile saperlo con certezza da dati OHLC a barre; su timeframe più
bassi il caso è più raro).

## 3. Live trading

Stesso comando con `--mode live` al posto di `--mode paper`. Chiede una conferma
esplicita scritta perché usa soldi veri. **Da fare solo dopo un paper trading
soddisfacente per un periodo adeguato.**

## Aggiungere una nuova strategia (pattern Strategy)

Basta creare una classe che estende `strategies.base.Strategy` e implementa
`on_market_event`. Non serve toccare nient'altro: engine, broker, risk manager
restano invariati. Esempio minimo:

```python
from strategies.base import Strategy
from core.events import SignalEvent, SignalType

class MiaStrategia(Strategy):
    def on_market_event(self, event):
        if <condizione>:
            return SignalEvent(event.symbol, event.timestamp, SignalType.LONG)
        return None
```

Poi in `backtest/run_backtest.py` (o `live/run_live.py`) si sostituisce
`EMACrossStrategy(...)` con `MiaStrategia(...)`.

## Limiti noti di questo scheletro (da affinare in base ai prossimi test)

- `summary_stats()` in `core/portfolio.py` annualizza lo Sharpe assumendo barre
  giornaliere: da adattare al timeframe reale.
- `CCXTBroker.get_equity()` somma solo il saldo USDT: per portafogli multi-asset
  serve convertire ogni asset al prezzo corrente.
- Nessuna gestione di riconnessione/retry sul feed live in caso di errori di rete
  dell'exchange: da aggiungere prima di un uso prolungato.
- Nessuno stop-loss/take-profit nel RiskManager di esempio: solo sizing.
