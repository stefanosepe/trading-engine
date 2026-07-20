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

## Calibrazione su screenshot reali (2026-07-20)

L'utente ha caricato 661 screenshot reali (Discord, 2021-2023) di trade BUD —
sia desktop TradingView/Bybit con P&L visibile, sia mobile Binance con
EMA5/10/60/223 esplicitamente etichettate. Analizzati tutti (17 batch da ~40
immagini ciascuno, via subagent paralleli). Convergenza molto forte su alcuni
punti, nonostante il campione sia quasi tutto crypto low-cap 1m e quasi tutto
LONG (pochissimi short osservati: LUNA, MDX, REQ, OG — insufficienti per
validare/smentire la simmetria long/short assunta da `BUDBidirectionalStrategy`).

**Conferme dirette del codice attuale:**
- EMA5/EMA10/EMA60/EMA223 sono esattamente le medie usate dall'utente (viste
  etichettate esplicitamente in piu' screenshot mobile) — coerente con
  `ema_fast_period=5, ema_stop_period=10, ema_trend_period=60`. EMA223 e'
  sempre visibile sui grafici ma mai citata come riferimento di regola
  (probabile solo contesto visivo di trend lunghissimo)
- Trigger su tocco preciso di EMA10 ("ema 10 perfezione", label ricorrente in
  decine di screenshot) — conferma la logica dell'innesco
- Stop = EMA10 al setup — confermato esplicitamente e ripetutamente
  ("Stop ema 10" scritto a mano su moltissimi screenshot), ma **molto piu'
  stretto/aderente all'EMA10 di quanto un buffer ATR ampio suggerisca**
- Filtro di trend: il prezzo e' sempre sopra l'EMA lenta al momento
  dell'entrata; confermato anche su 2 asset non-crypto (azioni Telecom
  Italia, UCG) con EMA piu' lenta (coerente col ramo EMA50 del codice)

**Scoperte che CONTRADDICONO o estendono la logica attuale:**
1. **Take profit — la scoperta piu' importante.** In NESSUNO dei 661
   screenshot il TP e' un multiplo R fisso, e in NESSUNO e' visibile o
   deducibile un riferimento a "prima EMA del timeframe superiore" (mai
   mostrato un overlay multi-timeframe). Il pattern e' fortissimo e
   ripetuto identico in tutti e 17 i batch: **il TP e' quasi sempre un
   livello di prezzo/resistenza orizzontale preesistente** — uno swing
   high/low precedente, "Max Giornata"/"Max ieri", un ATH, o una linea
   disegnata a mano dall'utente — spesso con uscite scalate su piu' livelli
   o gestione discrezionale (ordini modificati/annullati durante il trade).
   I guadagni realizzati variano moltissimo (1.5%-16%+), incompatibili con
   un R:R fisso. **`tp_r_multiple=2.0` va sostituito con una logica "target =
   prossimo swing high/resistenza significativa sullo stesso timeframe"** —
   piu' facile da implementare rispetto all'idea originale (non serve un
   secondo DataFeed multi-timeframe), ma richiede un detector di swing
   high/low sui dati gia' disponibili
2. **"Bud Fintato"** (falso breakout) — concetto nominato esplicitamente
   dall'utente in molti screenshot: un primo tentativo di rottura fallisce/
   ritraccia, poi arriva la vera rottura che genera il trade. Non esiste
   alcun meccanismo simile nel codice attuale (ne' in `bud_strategy.py` ne'
   in `third_touch.py`, sebbene quest'ultimo — gia' scritto ma con
   `require_third_touch=False` di default — copra una logica di "tocchi
   multipli" concettualmente vicina)
3. **Rilevamento BUD via livello testato piu' volte** — spesso il "Bud" non
   e' una singola candela di espansione ma una **resistenza orizzontale
   testata 2-3 volte** ("1,2,3" annotato a mano, "terzo tocco") prima della
   rottura vera. La regola attuale (sequenza di >= 3 candele verdi con
   ultima candela ad espansione >= 1.5x) coglie solo un sottoinsieme dei
   casi reali — il pattern "singola candela spike enorme" e' altrettanto
   comune, e il pattern "livello testato piu' volte" e' probabilmente il
   piu' comune di tutti. `ThirdTouchDetector` (gia' nel codice, opzionale)
   sembra il pezzo giusto per modellare questo, ma andrebbe reso piu'
   centrale invece che un filtro opzionale aggiuntivo
4. **Trigger meno rigido di quanto assunto**: l'entrata scatta spesso alla
   rottura del massimo della base di appoggio (ordine stop-buy piazzato
   esattamente li'), non necessariamente dopo una specifica "candela di
   innesco a range contratto" — `innesco_contraction_ratio=0.5` puo' essere
   troppo restrittivo e scartare setup validi che il fallback (BUD stesso
   come trigger) dovrebbe gia' parzialmente coprire
5. **Appoggio piu' vario**: da 1-2 candele fino a 15-40 in alcuni casi
   (accumulo lungo prima dello spike) — `appoggio_max_candles=6` e' spesso
   troppo stretto
6. **Gestione dinamica non modellata**: alcuni screenshot mostrano stop
   spostato a breakeven dopo esecuzione parziale, TP modificato/annullato e
   ripiazzato durante il trade, ingressi scalati su piu' livelli
   ("primo ingresso"/"secondo ingresso", piramidazione) — tutto assente
   dall'infrastruttura attuale (Engine/Broker gestiscono un solo TP/SL
   fissato all'apertura)
7. Un'occorrenza isolata mostra lo stop ancorato a EMA60 invece che EMA10 —
   probabile eccezione/caso limite, non abbastanza frequente da cambiare la
   regola di default

**Nota sul campione**: quasi tutti gli screenshot mostrano trade vincenti
(probabile selection bias — l'utente condivide su Discord soprattutto le
vincite), quindi non e' possibile stimare un win rate realistico da questi
dati. I backtest gia' fatti (vedi sopra, PaperJournalBroker) restano l'unica
fonte per quello.

## TODO / prossimi passi aperti

1. **Implementare TP basato su swing high/low** (prossima resistenza/supporto
   sullo stesso timeframe) al posto del multiplo R fisso — la modifica di
   calibrazione piu' importante emersa dall'analisi degli screenshot, vedi
   sopra
2. **Modellare "Bud Fintato"** (tolleranza a un primo falso breakout prima
   del trigger valido) — da valutare se estendere `ThirdTouchDetector` o
   scrivere un meccanismo dedicato
3. Ricalibrare `bud_lookback_min` (valutare soglia piu' bassa/flessibile,
   dato che molti BUD reali sono singola candela spike) e
   `appoggio_max_candles` (valutare range piu' ampio)
4. **Commissioni/slippage nel PaperJournalBroker** — attualmente assenti, i
   risultati sono ottimistici rispetto alla realta'
5. **Verificare l'ipotesi long/short sbilanciato** su altri periodi/asset —
   il campione screenshot non aiuta qui (quasi solo long)
6. Valutare se modellare gestione dinamica (stop a breakeven, TP scalato,
   ingressi piramidati) — feature grossa, probabilmente fuori scope per ora
7. **ActivTrades come broker live**: verificato che offre API solo per clienti
   istituzionali, via WebSocket con client .NET ufficiale (nessun supporto Python
   documentato) — se si vuole andare live con questo broker serve un client
   custom, non e' un drop-in come CCXTBroker. Alternative piu' semplici da
   integrare: altri exchange crypto via ccxt, o broker con REST nativa
   (Alpaca, Interactive Brokers)
8. Ordini stop simulati a chiusura barra, non intrabar — approssimazione presente
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
