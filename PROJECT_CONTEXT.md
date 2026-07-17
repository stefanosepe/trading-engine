# Contesto del progetto — trading system BUD

Questo file esiste per dare a chi (o cosa) riprende il lavoro tutto il contesto
delle decisioni prese finora, senza dover rileggere la conversazione originale.
Scritto per essere usato come prompt/riferimento in Claude Code.

## Obiettivo generale

Infrastruttura per sviluppare, testare (backtest), validare (paper trading/journal)
ed eventualmente eseguire dal vivo strategie di trading — con le strategie
intercambiabili via pattern Strategy, così l'infrastruttura non cambia mai,
cambia solo la logica del segnale.

## Architettura (invariata, non ridiscuterla da zero)

Event-driven: `DataFeed → Strategy → RiskManager → Broker → Portfolio`, orchestrato
da un unico `Engine` (core/engine.py) che gira IDENTICO in backtest, paper e live —
cambiano solo le implementazioni concrete di `DataFeed` e `Broker` passate al
costruttore. Questo e' il principio guida di tutto il progetto: se una modifica
rompe questa invarianza, e' quasi certamente sbagliata.

Componenti:
- `core/events.py` — MarketEvent, SignalEvent (con stop_price/take_profit_price
  opzionali, decisi dalla strategia), OrderEvent, FillEvent
- `core/engine.py` — il loop. Blocca nuovi ingressi se `broker.has_open_position()`
  e' True (evita di sovrascrivere un trade aperto)
- `core/portfolio.py` — tracking equity/fill, statistiche (Sharpe approx, drawdown)
- `strategies/base.py` — interfaccia `Strategy.on_market_event() -> SignalEvent | None`
- `strategies/ema_cross.py` — esempio semplice, incrocio EMA
- `strategies/bud_strategy.py` — la strategia vera (vedi sezione dedicata sotto)
- `strategies/bud_bidirectional.py` — wrapper che ottiene lo short "ribaltando"
  i dati (open'=-open, high'=-low, low'=-high, close'=-close) e riusando la
  stessa `BUDStrategy` — NON duplicare la logica per lo short altrove
- `risk/manager.py` — due RiskManager: `FixedFractionalRiskManager` (% equity,
  usato dall'esempio EMA cross) e `FixedRiskPerTradeManager` (rischio fisso in
  valuta, usato da BUD — legge stop_price dal segnale, calcola size di conseguenza)
- `broker/backtest_broker.py` — fill istantanei simulati, con commissioni/slippage
- `broker/paper_journal_broker.py` — **il broker usato per tutti i test BUD finora**:
  non esegue nulla di reale, apre trade virtuali con TP/SL e li risolve da solo
  quando il prezzo li tocca (via `check_pending`, chiamato dall'Engine ad ogni
  barra). NON applica commissioni/slippage (tutti i risultati riportati sono al
  lordo dei costi di transazione — tenerne conto prima di trarre conclusioni)
- `broker/ccxt_broker.py` — per paper/live reali su exchange crypto (via ccxt),
  non ancora testato in questa fase, solo scaffolding
- `data/feed.py` — `CSVDataFeed` (backtest) e `CCXTLiveDataFeed` (paper/live,
  dati pubblici senza API key)
- `journal/` — tutti i runner di test fatti finora (vedi sotto)

## La strategia BUD — specifica completa

Nome dato dall'utente (da "Bud Spencer"). Logica derivata da screenshot TradingView
che l'utente ha (non ancora caricati/analizzati per calibrazione — vedi TODO).

### Idea di fondo
Prezzo in trend forte sopra EMA5 ("in viagra") che sbatte contro un livello di
resistenza (BUD), forma uno spike di rigetto, poi fa una fase di "appoggio" sopra
EMA10 (se EMA10 tiene, e' un segnale di forza nonostante il rigetto). Dentro la
fase di appoggio si cerca una candela "piccina" (contrazione di range) che sfiora
EMA10 senza chiuderci sotto — quella e' il punto di innesco per anticipare
l'entrata (altrimenti un ordine stop-buy esattamente sul livello BUD spesso non
filla per l'effetto "tappo di champagne", cioe' gap/espansione improvvisa).

### Regole (implementate in strategies/bud_strategy.py)
1. **Rilevamento BUD**: sequenza di >= `bud_lookback_min` candele verdi consecutive
   con close > EMA5. Se l'ultima ha range >= `bud_expansion_mult` × media range
   delle precedenti nella sequenza → BUD = high di quella candela
2. **Fase di appoggio**: candele successive che NON chiudono sotto EMA10.
   Chiusura sotto EMA10 = invalidazione, si torna a scansionare
3. **Candela di innesco**: dentro l'appoggio, prima candela con range <=
   `innesco_contraction_ratio` × media range appoggio, il cui low tocca EMA10
   (con piccola tolleranza) senza chiuderci sotto → trigger = high di questa candela
4. **Fallback**: se non emerge un innesco entro `appoggio_max_candles`, si usa
   BUD stesso come trigger (fill meno affidabile, ma meglio di niente)
5. **Entrata**: rottura del trigger (candela successiva con high >= trigger)
6. **Filtro di trend** (aggiunto su richiesta esplicita dell'utente): mai
   controtrend. Al momento dell'entrata, il prezzo deve essere sopra
   `ema_trend_period` (default 60 per crypto, 50 per azionario/indici/commodity
   secondo l'utente — resta un parametro libero). Se il filtro fallisce, il setup
   viene scartato (nessun segnale)
7. **Stop loss**: EMA10 al momento del setup - buffer (`stop_buffer_atr_mult` × ATR)
8. **Take profit**: **SEMPLIFICAZIONE IMPORTANTE** — la regola originale
   dell'utente era "prima EMA sul timeframe superiore", MAI implementata (richiede
   un secondo DataFeed sincronizzato). Il codice usa sempre un multiplo R fisso
   (`tp_r_multiple`, default 2.0) come proxy. Se si vuole essere fedeli alla
   specifica originale, questo e' il pezzo mancante piu' importante.
9. **Position sizing**: rischio fisso in valuta per trade (non % equity) —
   `size = risk_per_trade / (entry - stop)`, implementato in
   `FixedRiskPerTradeManager`

### Short = long su dati ribaltati
L'utente ha confermato esplicitamente che il meccanismo e' "ribaltabile al 100%":
nessuna asimmetria tra long e short. Per questo `BUDBidirectionalStrategy` non
duplica la logica ma ribalta i dati (vedi sopra). Se in futuro emergono asimmetrie
reali (es. dallo studio degli screenshot), sara' necessario rivedere questa scelta.

### Parametri attuali (mai calibrati su dati reali dell'utente — vedi TODO)
```python
ema_fast_period=5, ema_stop_period=10, ema_trend_period=60|50,
bud_lookback_min=3, bud_expansion_mult=1.5,
appoggio_min_candles=1, appoggio_max_candles=6,
innesco_contraction_ratio=0.5, atr_period=14,
stop_buffer_atr_mult=0.25, tp_r_multiple=2.0
```
Sono TUTTI numeri di partenza plausibili, MAI calibrati sui veri screenshot che
l'utente possiede. Non trattarli come validati.

## Risultati dei test fatti finora (tutti con PaperJournalBroker, no commissioni)

**BTC/USDT** (dati storici reali, scaricati da GitHub — vedi TODO su come procurarsi
dati, i CSV non sono versionati nel repo):
| TF | Periodo | Trade | Win rate | PnL (in R) |
|---|---|---|---|---|
| 5m | ~4 mesi 2019 | 264 | 31.8% | -12R (sotto breakeven, che e' 33.3% con R:R 1:2) |
| 30m | ~4 mesi 2019 | 62 | 40.3% | +13R |
| 1h | ~6 mesi 2019 | 33 | 45.5% | +12R |
| 1h | 2017-2019 (2.3 anni) | 162 | 39.5% | +30R, long/short bilanciati (40.7%/38.0%) |

**Gold / Nasdaq100 / Crude Oil** (2019, con filtro trend EMA50 attivo):
| Asset | TF | Trade | Win rate | Note |
|---|---|---|---|---|
| Gold | 1h | 60 | 33.3% | Short molto peggio del long (19% vs 41%) |
| Nasdaq100 | 1h | 59 | 30.5% | Stesso pattern: short 19% vs long 37% |
| Crude Oil | 1h | 49 | 49.0% | Long e short entrambi ok, il migliore dei tre |
| Gold/Nasdaq/Oil | 4h | 16-25 | 36-44% | Campioni troppo piccoli per conclusioni |

Ipotesi non verificata: nel 2019 oro e nasdaq erano in trend rialzista marcato,
quindi le poche short che passano il filtro di trend sono probabilmente
correzioni temporanee dentro un trend piu' ampio, sfavorevoli per costruzione.
Andrebbe testato su periodi/asset con trend ribassista per capire se e' un
problema strutturale della strategia o solo di questo campione.

## TODO / prossimi passi aperti

1. **Calibrazione sui veri screenshot dell'utente** — questo e' IL prossimo passo,
   l'utente deve ancora scaricarli. Finche' non e' fatto, tutti i parametri sopra
   sono placeholder
2. **TP multi-timeframe reale** ("prima EMA sul TF superiore") — attualmente solo
   R-multiple fisso, e' una semplificazione nota
3. **Commissioni/slippage nel PaperJournalBroker** — attualmente assenti, i
   risultati sono ottimistici rispetto alla realta'
4. **Verificare l'ipotesi long/short sbilanciato** su altri periodi/asset
5. **ActivTrades come broker live**: verificato che offre API solo per clienti
   istituzionali, via WebSocket con client .NET ufficiale (nessun supporto Python
   documentato) — se si vuole andare live con questo broker serve un client
   custom, non e' un drop-in come CCXTBroker. Alternative piu' semplici da
   integrare: altri exchange crypto via ccxt, o broker con REST nativa
   (Alpaca, Interactive Brokers)
6. Ordini stop simulati a chiusura barra, non intrabar — approssimazione presente
   in tutto il sistema, da tenere a mente specialmente sui timeframe piu' bassi

## Come rigenerare i dati usati nei test (non versionati nel repo)

```bash
# BTC/USDT 1h (da GitHub, dataset cryptobigbro/binance-BTCUSDT)
curl -sL "https://raw.githubusercontent.com/cryptobigbro/binance-BTCUSDT/master/binance-BTCUSDT-1h.csv" -o btc_raw.csv
# poi convertire con pandas al formato timestamp,open,high,low,close,volume
# (vedi cronologia comandi bash in questa sessione per lo script esatto)

# Gold/Nasdaq100/Crude Oil 2019 1h/4h (da GitHub, FutureSharks/financial-data,
# dati minuto Oanda ricampionati)
# repo grande (~870MB tarball completo) — estrarre solo le cartelle/anni serviti:
#   pyfinancialdata/data/currencies/oanda/{NAS100_USD,WTICO_USD,XAU_USD}/2019/
```

## Runner disponibili in journal/

- `run_journal_backtest.py` / `run_journal_live.py` — journal generico con
  EMACrossStrategy (esempio, non BUD)
- `run_bud_backtest.py` — BUD solo long, su BTC
- `run_bud_bidirectional_backtest.py --dataset {short,full,5m,30m}` — BUD
  bidirezionale su BTC, vari timeframe/periodi
- `run_bud_multi_asset.py --asset {gold,nasdaq100,crudeoil} --tf {1h,4h}` — BUD
  bidirezionale + filtro trend su altri asset
