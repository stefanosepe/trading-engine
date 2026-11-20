# Trading System — scheletro infrastrutturale

[![tests](https://github.com/stefanosepe/tradingBot/actions/workflows/tests.yml/badge.svg)](https://github.com/stefanosepe/tradingBot/actions/workflows/tests.yml)

Architettura event-driven: `DataFeed → Strategy → RiskManager → Broker → Portfolio`.
Lo stesso `Engine` (core/engine.py) gira identico in backtest, paper trading e live:
cambiano solo le implementazioni concrete di `DataFeed` e `Broker` che gli vengono
passate. Questo evita il problema più comune (logica diversa tra backtest e live che
diverge nel tempo).

## Come è stato costruito

Il progetto è sviluppato con **Claude Code** come agente di coding, con me nel ruolo di
chi progetta, decide e verifica. Il metodo:

- **Architettura decisa prima del codice.** L'invarianza dell'`Engine` tra backtest,
  paper e live è un vincolo fissato all'inizio: ogni modifica proposta dall'agente
  viene valutata rispetto a quel principio.
- **Contesto persistente per l'agente.** [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)
  raccoglie architettura, specifica della strategia, decisioni prese, risultati e TODO.
  Ogni sessione riparte da lì invece che dalla conversazione precedente, e le scelte
  da non rimettere in discussione sono scritte in modo esplicito.
- **Semplificazioni dichiarate.** Dove l'implementazione si discosta dalla specifica
  (TP a multiplo R fisso invece della EMA sul timeframe superiore, assenza di
  commissioni nel journal, ordini stop simulati a chiusura barra) la differenza è
  documentata invece di essere nascosta.
- **Verifica su dati reali.** Ogni strategia passa da backtest su più asset e
  timeframe prima di qualsiasi uso live; le modifiche vengono confrontate con i
  risultati precedenti per escludere regressioni.
- **Test automatici** in [`tests/`](tests/) sulle parti critiche (sizing a rischio fisso,
  risoluzione TP/SL, simmetria long/short), eseguiti in CI a ogni push.

## Strategia BUD

Oltre all'esempio EMA cross, il repository contiene `BUDStrategy`: una strategia di
breakout su resistenza con fase di "appoggio" sulla EMA10, filtro di trend e rischio
fisso per trade. Lo short è ottenuto riusando la stessa logica su dati ribaltati
(`BUDBidirectionalStrategy`), senza duplicare codice. Specifica completa, parametri e
risultati dei test sono in [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md).

> I risultati riportati sono al lordo dei costi di transazione e con parametri non
> ancora calibrati: servono a validare l'infrastruttura, non a promettere rendimenti.

## Struttura

```
core/        events.py (i messaggi che circolano), engine.py (il loop), portfolio.py
strategies/  base.py (interfaccia Strategy), ema_cross.py (esempio), bud_strategy.py,
             bud_bidirectional.py (BUD long/short)
risk/        manager.py (trasforma segnali in ordini dimensionati)
broker/      base.py (interfaccia), backtest_broker.py (simulato),
             paper_journal_broker.py (trade virtuali con TP/SL), ccxt_broker.py (paper/live)
data/        feed.py (CSV per backtest, ccxt polling per paper/live)
backtest/    run_backtest.py
journal/     runner dei test BUD su BTC e multi-asset
live/        run_live.py (paper trading e live trading, stesso script)
tests/       test automatici (pytest)
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
