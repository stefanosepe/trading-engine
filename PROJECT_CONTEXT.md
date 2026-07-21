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

## Calibrazione su "terzo tocco" + "candelina" (376 screenshot, 2026-07-20)

Secondo giro di screenshot, stavolta organizzati dall'utente in due cartelle
dedicate (`data/terzo tocco/`, `data/candelina/`) per calibrare
specificamente `strategies/third_touch.py` (ThirdTouchDetector) e la logica
di "innesco" gia' in `bud_strategy.py`. Spiegazione dell'utente della catena
completa: avvicinamento multi-giorno a un livello -> 3° tocco -> sotto il
livello del 3° tocco si forma un BUD -> sotto il livello BUD si forma una
"candelina" (candela piccola/compressa, schiacciata tra BUD ed EMA10, che
non chiude sotto EMA10) -> ingresso anticipato sulla candelina.

**Scoperta piu' importante: il timeframe assunto nel codice e' sbagliato.**
Il docstring di `ThirdTouchDetector` dice esplicitamente "pensato per
timeframe alti (4h, 1d, weekly): su timeframe bassi il rumore genera troppi
pivot poco significativi". Su tutti e 7 i batch analizzati (237 screenshot
unici), la stragrande maggioranza del pattern reale e' osservata su **1m e
5m**, con 30m minoritario e 4h/1d rari eccezioni. La "costruzione su piu'
giorni" descritta a parole si traduce quasi sempre in "multi-ora" o anche
"multi-decina di minuti" sul grafico reale — l'utente scala su timeframe
molto piu' bassi di quanto la logica attuale assuma.

Altri dettagli sul terzo tocco:
- Numero di tocchi non sempre 3: osservati anche 2 e 4 tocchi prima del
  breakout — "terzo tocco" e' piu' il nome del pattern che un conteggio
  rigido
- Tolleranza reale tra tocchi tipicamente stretta (0.2-0.5%), coerente con
  `tolerance_pct=0.005` attuale
- Distanza in candele tra tocchi molto variabile (5-50+), nessun intervallo
  fisso
- Spesso il "livello" non e' un pivot singolo pulito ma un plateau/cluster
  toccato molte volte ravvicinate (accumulo), non 3 pivot isolati distinti
- La catena completa (3° tocco + BUD + candelina) e' raramente annotata
  per intero nello stesso screenshot; quando lo e', le tre fasi spesso
  "collassano" quasi nello stesso punto del grafico invece di essere
  nettamente separate nel tempo
- Un caso (EPS/USDT) mostra lo stesso setup confermato sia su 30m sia su
  1D con la stessa numerazione — spunto per una possibile validazione
  multi-timeframe, non implementata

Dettagli sulla candelina (confermano bene la logica gia' scritta in
`_handle_appoggio`):
- Compressione tipica 30-60% del range delle candele di appoggio circostanti
  — coerente con `innesco_contraction_ratio=0.5`
- Tocco EMA (spesso EMA10, ma in alcuni screenshot EMA5/EMA60/EMA223 a
  seconda del setup/timeframe — la EMA "di comando" non e' sempre fissa a
  10) confermato ripetutamente e con label esplicite ("Stop ema 10", "ema10
  perfezione", "candela di riposo sul supporto", "candela di azzeramento")
- Candele di appoggio precedenti: molto variabile, 2-6 nella maggioranza dei
  casi ma piu' fasci (NKNUSDT ~8-10, RGT/PLA/SPARTA/FIS 15-20+) superano
  `appoggio_max_candles=6` — segnale medio, non abbastanza netto da
  giustificare un cambio di default senza backtest (vedi sotto, gia'
  provato ad alzarlo su BTC 1h con risultato negativo)
- Entrata confermata sempre alla rottura dell'high della candelina, coerente
  col codice

**Verifica empirica: ThirdTouchDetector ora bug-fixed, testato su 5m/30m
(il timeframe reale, non piu' solo 1h) con costi realistici** (0.1%/lato +
0.05% slippage, BTC/USDT, dataset 2019 e 2017-2019 ricampionati da dati 1m):

| TF | Periodo | Config | n | Win rate | PnL |
|---|---|---|---|---|---|
| 5m | corto | baseline | 260 | 24.2% | -3024 |
| 5m | corto | third_touch obbligatorio | 69 | 29.0% | -682 |
| 5m | lungo | baseline | 2057 | 28.4% | -16953 |
| 5m | lungo | third_touch obbligatorio | 769 | 29.4% | -5787 |
| 30m | corto | baseline | 45 | 26.7% | -330 |
| 30m | corto | third_touch obbligatorio | 15 | 13.3% | -156 |
| 30m | lungo | baseline | 316 | 38.3% | -695 |
| 30m | lungo | third_touch obbligatorio | 146 | 39.0% | -309 |

Anche **senza alcun costo di transazione**, 5m resta netto negativo
(baseline -1022, third-touch -484 su ~2000/770 trade) — conferma la nota
storica gia' presente in questo documento ("5m ~4 mesi 2019: -12R, sotto
breakeven"). Il filtro terzo tocco, ora corretto anche sul lato short,
**riduce sistematicamente il numero di trade (filtra per qualita') e
dimezza circa le perdite nella maggior parte dei casi**, ma non porta MAI
la strategia in territorio positivo su nessuna combinazione TF/periodo
testata. **Conclusione onesta: con la logica di TP a 2R fisso, BUD non e'
profittevole su BTC a nessun timeframe testato (5m, 30m, 1h) — il problema
non e' (solo) la qualita' del filtro d'ingresso, e' la struttura
rischio/rendimento del sistema.**

Provata anche la combinazione swing TP + third_touch su 5m/30m (stesso
dataset, stessi costi): **il risultato e' NEGATIVO, in ogni combinazione
peggiora rispetto al solo third_touch** (es. 5m: third_touch da solo -5787,
+ swing p=2 -5892/-6113; 30m: third_touch da solo -309, + swing p=2
-643/-471). Conferma su timeframe diversi la conclusione gia' vista su 1h:
lo swing TP scambia win rate con reward medio piu' piccolo, e non e' una
buona idea combinarlo col filtro terzo tocco. **La configurazione migliore
trovata finora resta "solo third_touch obbligatorio, TP 2R fisso"** — non
profittevole, ma quella che perde meno su tutti i timeframe/periodi testati.

## Implementazione della calibrazione e verifica via backtest (2026-07-20)

Fatto un primo giro di implementazione + verifica empirica su BTC/USDT 1h
(dataset "short" ~4 mesi 2019, 17-34 trade a seconda dei parametri; dataset
"full" 2017-2019, 129-301 trade) per non fidarsi ciecamente delle impressioni
qualitative dagli screenshot. Risultati:

- **`SwingLevelTracker` (nuovo file `strategies/swing_levels.py`) +
  `use_swing_tp` in `BUDStrategy`**: implementato e funzionante — quando
  attivo, il take profit e' il prossimo swing high non ancora rotto sopra
  l'entrata invece del multiplo R fisso, esattamente come osservato negli
  screenshot. PERO' il backtest mostra che la versione "prendi sempre il
  livello piu' vicino" alza molto il win rate (fino al 63% su alcuni
  sotto-periodi, dataset full: 40%->64% con `swing_pivot_lookback=3`) ma
  **abbassa il PnL netto** rispetto al 2R fisso (dataset full: +330 col 2R
  fisso vs +172/+100/+80 a seconda di `swing_pivot_lookback` 3/8/20 con lo
  swing TP) — taglia corto i trade migliori. Coerente con quanto notato negli
  screenshot stessi: spesso ci sono uscite scalate o target estesi oltre il
  primo livello (misura/estensione), comportamento che qui non e' modellato.
  **Lasciato `use_swing_tp=False` di default** (fallback sicuro sul 2R),
  il meccanismo resta disponibile e testato per chi vuole sperimentarci o
  affinarlo (es. combinarlo con un'estensione oltre il primo livello, o
  uscite parziali)
- **Ricalibrazione di `bud_lookback_min`/`appoggio_max_candles`**: provato ad
  abbassare/allargare come suggerivano gli screenshot, ma il risultato e'
  stato incoerente tra i due dataset (es. `bud_lookback_min=2` da solo:
  -40 sul dataset corto ma +710 sul dataset lungo; `appoggio_max_candles=10`
  peggiora in entrambi) — **troppo rumoroso per trarre conclusioni da un
  singolo asset/venue**, quindi i default restano quelli originali (3 e 6),
  gia' validati dai backtest storici in questo documento. Da rivisitare con
  un vero parameter sweep multi-asset se si vuole insistere su questa strada
- Non implementati in questo giro (troppo ampi per una singola iterazione,
  richiedono modifiche architetturali piu' profonde): **"Bud Fintato"**
  (tolleranza a un primo falso breakout), **rilevamento BUD via livello
  multi-touch** come meccanismo primario (c'e' gia' `ThirdTouchDetector` ma
  resta opzionale/`require_third_touch=False`), **gestione dinamica del
  trade** (breakeven, TP scalato, ingressi piramidati — richiede che
  Engine/Broker sappiano gestire piu' di un TP/SL fissato all'apertura)

## Code review (Fable 5) + bug fix + costi di transazione (2026-07-20)

Doppia review indipendente dell'algoritmo (review preliminare + Fable 5 con
verifica empirica su dati sintetici). Esito chiave: **nessun lookahead bias**
nella catena swing TP (verificata l'intera sequenza temporale), ma il win
rate 69% osservato era in gran parte artefatto geometrico: con
`swing_pivot_lookback=2` il massimo del BUD stesso viene confermato come
pivot durante l'appoggio e diventa il target — vicino, quindi facile da
colpire (baseline casuale con TP a 0.65R ≈ 61%).

Bug trovati e FIXATI in questo giro:
1. `third_touch.py` + `_has_third_touch_confluence`: divisioni per
   `level.price` senza `abs()` — col lato short (prezzi ribaltati/negativi)
   i confronti percentuali erano sempre veri: clustering dei livelli e
   filtro terzo tocco erano ROTTI sul lato short. NB: le colonne short della
   grid search terzo-tocco fatta in precedenza non sono attendibili
2. `bud_strategy.py`: tolleranza innesco `ema_stop * 1.001` → banda
   ribaltata dalla parte sbagliata con EMA negativa (short piu' severo del
   long di ~0.2%). Ora additiva con `abs()`
3. `core/engine.py`: `_current_position` non veniva decrementato quando
   `check_pending` chiudeva un trade a TP/SL — stato sporco, innocuo per BUD
   ma un EXIT successivo avrebbe aperto un trade fantasma
4. `PaperJournalBroker`: aggiunti `commission_pct` (per lato) e
   `slippage_pct` (solo su fill market/stop: entrata e SL; il TP e' limit,
   fillato esatto). Default 0 per riproducibilita' dei risultati storici
5. `FixedRiskPerTradeManager`: aggiunto `max_notional` opzionale (cap sulla
   size quando lo stop e' quasi a ridosso dell'entrata — in live una size
   1000x il rischio sarebbe ineseguibile)
6. `BUDStrategy`: nuovo `swing_tp_min_r` — il target swing non e' piu' il
   primo livello sopra l'entrata ma il primo sopra `entry + minR * rischio`
   (scarta i target-briciola tipo il massimo del BUD stesso). Warm-up reso
   coerente: swing tracker e third-touch osservano tutte le barre dalla prima
Non fixato (documentato): priorita' silenziosa del long sullo short quando
entrambi scattano sulla stessa barra nel wrapper bidirezionale; fill degli
stop senza gap (ottimista su asset con gap overnight: gold/nasdaq/oil);
statistiche di `Portfolio.summary_stats` fuorvianti (contano i fill, Sharpe
assume barre daily) — i numeri BUD vengono da `broker.stats()`, non da li'.

**Risultati CON costi realistici (0.1%/lato + 0.05% slippage, BTC/USDT 1h
2017-2019, `max_notional=5000`):**
| Config | n | Win rate | PnL netto |
|---|---|---|---|
| 2R fisso | 156 | 40.4% | -9 (da +330 senza costi) |
| swing p=2 | 177 | 55.9% | -139 |
| swing p=2 + floor 1.0R | 176 | 51.7% | -163 |
| swing p=2 + floor 1.5R | 175 | 51.4% | -89 |
| swing p=3 + floor 1.0R | 171 | 48.0% | -199 |

**Conclusione onesta: al netto dei costi NESSUNA configurazione e' oggi
profittevole su BTC 1h.** Il 2R fisso e' ~breakeven, le varianti swing
peggio (target medi piccoli = i costi pesano proporzionalmente di piu').
L'obiettivo "win rate >= 60%" e' raggiungibile meccanicamente coi target
vicini (69% senza costi) ma non produce expectancy positiva: il vero
obiettivo deve essere l'EV netto, non il win rate. Le leve realistiche per
migliorare l'EV: (a) ridurre i costi relativi con timeframe piu' alti o
stop piu' ampi (nozionale minore a parita' di rischio), (b) migliorare la
selezione dei segnali (filtri di qualita': trend piu' forte, terzo tocco ora
che e' fixato anche sul lato short, volume), (c) uscite scalate/trailing
come negli screenshot reali (richiede estensione di Engine/Broker).

## TODO / prossimi passi aperti

1. **Il vincolo che conta adesso: BUD a 2R fisso non e' profittevole su BTC
   a NESSUN timeframe/periodo testato (5m, 30m, 1h) con costi realistici** —
   ne' con third_touch, ne' con swing TP, ne' con la combinazione. Prima di
   inseguire altri filtri/parametri, vale la pena chiedersi se il problema
   e' strutturale al 2R fisso (vedi punto 2) o alla strategia stessa su
   questo asset — provare su asset/periodi diversi (punto 3) prima di
   continuare a ottimizzare solo su BTC
2. **Ripensare il TP oltre lo swing-al-livello-piu'-vicino**: idee dagli
   screenshot non ancora provate — estensione oltre il primo livello quando
   il momentum e' forte, uscite parziali/scalate (piu' fedeli a quanto
   osservato: gli utenti spesso non escono al primo livello). Il floor
   minimo in R (`swing_tp_min_r`) e' implementato ma testato solo da solo,
   non in combinazione con third_touch (dove non ha aiutato)
3. Un vero parameter sweep (multi-asset, multi-periodo, multi-timeframe)
   invece di singoli A/B su BTC — nessun tentativo fatto finora ha dato
   segnale pulito e coerente tra timeframe/periodi diversi
4. **Verificare l'ipotesi long/short sbilanciato** su altri periodi/asset —
   il campione screenshot non aiuta qui (quasi solo long)
5. Valutare se modellare gestione dinamica (stop a breakeven, TP scalato,
   ingressi piramidati) — feature grossa, probabilmente fuori scope per ora,
   ma coerente con piu' pattern osservati negli screenshot (uscite scalate,
   secondo ingresso)
6. **ActivTrades come broker live**: verificato che offre API solo per clienti
   istituzionali, via WebSocket con client .NET ufficiale (nessun supporto Python
   documentato) — se si vuole andare live con questo broker serve un client
   custom, non e' un drop-in come CCXTBroker. Alternative piu' semplici da
   integrare: altri exchange crypto via ccxt, o broker con REST nativa
   (Alpaca, Interactive Brokers)
7. Ordini stop simulati a chiusura barra, non intrabar — approssimazione presente
   in tutto il sistema, da tenere a mente specialmente sui timeframe piu' bassi

## Come rigenerare i dati usati nei test (non versionati nel repo)

```bash
# BTC/USDT 1h (da GitHub, dataset cryptobigbro/binance-BTCUSDT)
curl -sL "https://raw.githubusercontent.com/cryptobigbro/binance-BTCUSDT/master/binance-BTCUSDT-1h.csv" -o btc_raw.csv
python3 -c "
import pandas as pd
df = pd.read_csv('btc_raw.csv')
df['timestamp'] = pd.to_datetime(df['open_timestamp_utc'], unit='s')
out = df[['timestamp','open','high','low','close','volume']]
out[(out['timestamp'] >= '2019-01-01') & (out['timestamp'] < '2019-05-01')].to_csv('data/btcusdt_1h.csv', index=False)
out[(out['timestamp'] >= '2017-08-01') & (out['timestamp'] < '2019-11-01')].to_csv('data/btcusdt_1h_full.csv', index=False)
"

# Gold/Nasdaq100/Crude Oil 2019 1h/4h (da GitHub, FutureSharks/financial-data,
# dati minuto Oanda ricampionati)
# repo grande (~870MB tarball completo) — estrarre solo le cartelle/anni serviti:
#   pyfinancialdata/data/currencies/oanda/{NAS100_USD,WTICO_USD,XAU_USD}/2019/

# BTC/USDT 5m/30m: stesso repo cryptobigbro NON ha file 5m/30m diretti (404),
# solo 1m (~100MB) e 1h. Scaricare l'1m e ricampionare:
curl -sL "https://raw.githubusercontent.com/cryptobigbro/binance-BTCUSDT/master/binance-BTCUSDT-1m.csv" -o btc_1m_raw.csv
python3 -c "
import pandas as pd
df = pd.read_csv('btc_1m_raw.csv')
df['timestamp'] = pd.to_datetime(df['open_timestamp_utc'], unit='s')
df = df.set_index('timestamp')[['open','high','low','close','volume']]
for freq, label in [('5min','5m'), ('30min','30m')]:
    r = df.resample(freq).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna().reset_index()
    r[(r['timestamp'] >= '2019-01-01') & (r['timestamp'] < '2019-05-01')].to_csv(f'data/btcusdt_{label}.csv', index=False)
    r[(r['timestamp'] >= '2017-08-01') & (r['timestamp'] < '2019-11-01')].to_csv(f'data/btcusdt_{label}_full.csv', index=False)
"

# BTC/USD 2022-2025 (cryptobigbro si ferma a nov 2019, serve altra fonte):
# repo ff137/bitstamp-btcusd-minute-data, dati Bitstamp 1min 2012-2025, gzippato
curl -sL "https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/main/data/historical/btcusd_bitstamp_1min_2012-2025.csv.gz" -o btc_bitstamp_1m.csv.gz
python3 -c "
import pandas as pd
df = pd.read_csv('btc_bitstamp_1m.csv.gz', compression='gzip')
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
df = df.set_index('timestamp')[['open','high','low','close','volume']]
recent = df[df.index >= '2022-01-01']
for freq, label in [('1h','1h'), ('4h','4h'), ('1D','1d')]:
    r = recent.resample(freq).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna().reset_index()
    r.to_csv(f'data/btcusdt_{label}_recent.csv', index=False)
"

# Gold/Nasdaq100/Crude Oil (Oanda, dati minuto): git clone diretto NON
# funziona da questo ambiente (github.com HTTPS 403), ma sparse-checkout con
# --filter=blob:none si', perche' passa dal protocollo git, non da HTTP semplice
git clone --filter=blob:none --sparse --depth 1 https://github.com/FutureSharks/financial-data.git fsdata
cd fsdata
git sparse-checkout set pyfinancialdata/data/currencies/oanda/NAS100_USD pyfinancialdata/data/currencies/oanda/WTICO_USD pyfinancialdata/data/currencies/oanda/XAU_USD
cd ..
python3 -c "
import pandas as pd, glob
FS = 'fsdata/pyfinancialdata/data/currencies/oanda'
for inst, label in [('XAU_USD','gold'), ('NAS100_USD','nasdaq100'), ('WTICO_USD','crudeoil')]:
    frames = [pd.read_csv(f) for year in (2018, 2019, 2020) for f in sorted(glob.glob(f'{FS}/{inst}/{year}/*.csv'))]
    df = pd.concat(frames, ignore_index=True)
    df['timestamp'] = pd.to_datetime(df['time'])
    df = df.set_index('timestamp')[['open','high','low','close','volume']].sort_index()
    df = df[~df.index.duplicated(keep='first')]
    r1h = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna().reset_index()
    r1h.to_csv(f'data/{label}_2018_2020_1h.csv', index=False)
"
# nota: dati disponibili fino a meta' 2020 in questo repo (non oltre), i file
# CSV hanno colonne time,close,high,low,open,volume (ordine diverso dal solito)
```

## Filtro "prossimita' massimo/minimo del giorno precedente" (2026-07-21)

Su richiesta esplicita dell'utente: il segnale long deve scattare in
prossimita' del massimo del giorno precedente (calendario UTC), il segnale
short in prossimita' del minimo di ieri. Implementato in `bud_strategy.py`:
- `_update_prev_day_high`: aggiorna il massimo del giorno in corso e, al
  cambio di giorno, congela quel massimo in `_prev_day_high` — nessun
  lookahead (il massimo del giorno N e' disponibile solo dal giorno N+1)
- Nuovi parametri: `require_prev_day_extreme` (default False, opt-in) e
  `prev_day_extreme_proximity_pct` (default 0.01 = 1%)
- Gate in `_fire_entry`, stesso pattern di `require_third_touch`: se il
  prezzo di rottura e' oltre la tolleranza dal massimo di ieri, niente
  segnale. Simmetria long/short automatica via il meccanismo di ribaltamento
  dati gia' esistente (nessun codice speciale per lo short, come per swing
  TP e terzo tocco)

**Risultati (BTC/USDT, costi realistici 0.1%/lato + 0.05% slippage):**

Prima scoperta: la tolleranza di default (1%) e' troppo larga — **piu' si
stringe, meglio va**, in modo consistente su tutti i timeframe testati (5m,
30m, 1h; provato fino a 0.15%). Con tolleranza larga il filtro non aggiunge
molto sopra il baseline; con tolleranza stretta (0.2-0.3%) filtra per
davvero i setup che sono *veramente* a ridosso del livello.

| TF | Periodo | Config | n | Win rate | PnL |
|---|---|---|---|---|---|
| 5m | lungo | baseline | 2057 | 28.4% | -16.953 |
| 5m | lungo | third_touch | 769 | 29.4% | -5.787 |
| 5m | lungo | prev_day 0.3% + third_touch | 48 | 33.3% | **-283** |
| 30m | lungo | baseline | 316 | 38.3% | -695 |
| 30m | lungo | prev_day 0.2% | 37 | 35.1% | -159 |
| **1h** | **lungo** | **prev_day 0.2%** | **28** | **46.4%** | **+33** |
| 1h | lungo | prev_day 0.15% | 24 | 45.8% | +33 |
| 1h | lungo | prev_day 0.25% | 31 | 45.2% | +24 |
| 1h | lungo | prev_day 0.3% | 33 | 42.4% | -4 |

**Primo risultato netto positivo dell'intera sessione**: su 1h (2017-2019),
tolleranza 0.15-0.25% da' win rate 45-46% (ben sopra il 33.3% di breakeven
per 2R) e PnL positivo, stabile su un range di soglie (non un singolo
numero fortunato) — segnale piu' credibile dei singoli picchi isolati visti
finora. ATTENZIONE pero': stesso filtro sullo stesso TF ma sul dataset
corto (4 mesi 2019, n=7) e' negativo — campione troppo piccolo per
confermare, e il dataset lungo pesa quasi tutto il 2017-2018 (bull market
BTC), quindi il risultato potrebbe non generalizzare a mercati laterali o
ribassisti. Su 5m/30m il filtro riduce le perdite ma non le azzera.

**Asimmetria long/short controllata e SCARTATA come falso segnale**: un
primo test su 30m mostrava lo short (vicino al minimo di ieri) nettamente
migliore del long (66.7%/+138 vs 11.8%/-110 di win rate/pnl) — ma lo stesso
confronto su 5m e 1h mostra l'OPPOSTO (long migliore dello short). Con
campioni di 17-20 trade per lato, questa oscillazione e' quasi certamente
rumore statistico, non un effetto strutturale reale — **non e' stata
introdotta nessuna asimmetria hard-coded nel filtro** per questo motivo,
resta simmetrico come tutto il resto della logica BUD.

**Prossimo passo naturale**: verificare la config `prev_day 0.15-0.25%` su
1h anche su altri asset (Gold/Nasdaq/Oil, gia' nel repo) e su BTC 2022-2025
(dataset `btc_recent` gia' scaricato in una sessione precedente, non
riverificato in questo giro) per capire se il segnale regge fuori dal bull
market 2017-2019 o e' specifico di quel regime.

## Validazione fuori campione: il segnale NON regge (2026-07-21)

Fatto subito il test suggerito sopra. **Esito: il segnale positivo su BTC
1h 2017-2019 non si generalizza.** Dati usati: BTC/USD Bitstamp 2022-2025
(`btcusdt_1h_recent.csv`, ricampionato da dati 1m — fonte diversa da
cryptobigbro perche' quel repo si ferma a novembre 2019, vedi sotto) e
Gold/Nasdaq100/Crude Oil Oanda 2018-2020 (`{gold,nasdaq100,crudeoil}_2018_2020_1h.csv`,
ricampionati da dati minuto via sparse-checkout del repo
FutureSharks/financial-data, stesso schema gia' noto).

| Asset | Periodo | prev_day 0.15-0.2% | Win rate | PnL |
|---|---|---|---|---|
| BTC | 2017-2019 (calibrazione) | si' | 45-46% | **+24/+33** |
| BTC | 2022-2025 (fuori campione) | si' | 29-35% | -91/-216 |
| BTC | 2022 / 2023 / 2024 (per anno) | si' | 33-36% | tutti negativi (-19/-21) |
| Gold | 2018-2020 | si' | 24-25% | -579/-938 |
| Nasdaq100 | 2018-2020 | si' | 19-22% | -441/-543 |
| Crude Oil | 2018-2020 | si' | 46-54% | **+36/+48** |

Due asset su cinque periodo/asset testati sono positivi (BTC 2017-2019,
Crude Oil 2018-2020), ma su periodi/asset diversi lo stesso filtro fallisce
nettamente. **Conclusione onesta: il filtro "prossimita' massimo/minimo di
ieri" non e' un edge robusto — funziona in alcuni regimi di mercato
specifici e fallisce in altri, lo stesso pattern gia' visto piu' volte in
questa sessione di calibrazione.** Non c'e' evidenza sufficiente per
consigliarne l'uso in produzione senza ulteriori dati/asset.

Nota su Crude Oil: il risultato positivo e' trainato quasi per intero dal
lato SHORT (68.8% win/+121 vs LONG 35.3%/-82) — probabile riflesso del
crollo del petrolio di inizio 2020 (prezzi negativi ad aprile 2020) dentro
questo specifico campione, non necessariamente un'asimmetria strutturale
long/short della strategia (stesso avvertimento gia' dato per BTC 30m: con
campioni piccoli, verificare sempre su piu' asset/periodi prima di fidarsi
di un'asimmetria).

**Bilancio complessivo della sessione di calibrazione**: nessuna
combinazione di filtri/parametri testata finora (third_touch, swing TP,
prev_day_extreme, da soli o combinati) produce un edge robusto e
consistente su asset/periodi diversi con costi realistici. I singoli
risultati positivi trovati sono sempre isolati a un asset/periodo
specifico e non sopravvivono al test fuori campione. Questo sposta il
sospetto dal "filtro d'ingresso sbagliato" a qualcosa di piu' strutturale:
il TP a multiplo R fisso (o la sua alternativa swing, ugualmente non
robusta), il timeframe scelto, o il fatto che i pattern osservati negli
screenshot Discord includono elementi mai modellati (uscite discrezionali,
piramidazione, gestione dinamica dello stop) che potrebbero essere proprio
cio' che rende profittevole il trading reale dell'utente rispetto a una
regola meccanica fissa.

## TP fisso %, invalidazione strutturale, e ipotesi di confluenza (2026-07-21)

Da un'analisi manuale con l'utente di un trade reale (BTC/USDT 1h, entrata
long il 18/07/2026), tre idee nuove, tutte implementate e testate:

**1. TP fisso in percentuale** (`fixed_tp_pct`) e **2. invalidazione
strutturale** (`invalidate_on_close_below_entry_level`, esce se una barra
CHIUDE sotto il livello di rottura invece di aspettare lo stop pieno).
Per implementare la seconda serviva sapere quando una posizione e' davvero
aperta/chiusa bar dopo bar (non solo al momento del segnale): aggiunto
`Strategy.on_fill` (default no-op, vedi `strategies/base.py`) chiamato da
`Engine._notify_fill` ad ogni fill, sia apertura sia chiusura.
`BUDBidirectionalStrategy.on_fill` inoltra a entrambe le istanze interne,
ribaltando direzione e prezzo per quella short. **Bug collegato scoperto e
fixato**: `PaperJournalBroker.execute_order` trattava OGNI ordine come
un'apertura — un EXIT per chiudere una posizione ne apriva invece una
nuova nella direzione opposta senza registrare l'esito del trade originale.
Ora riconosce un ordine di direzione opposta a un trade gia' aperto sulla
stessa chiave come chiusura (`_close_trade`, condivisa con `check_pending`).

Testate applicate come default UNIVERSALE a tutti i segnali BUD (non solo
al tipo di setup manualmente analizzato) su BTC 1h/5m/30m, storico e
recente: **entrambe peggiorano sistematicamente i risultati** — atteso,
dato che nascono dall'osservazione di un singolo trade specifico via
hindsight, non da un pattern generale. Il TP fisso all'1% specialmente e'
molto peggio del 2R fisso (win rate 10-17% invece di 30-40%): su molti
trade il target da 1% e' troppo lontano rispetto allo stop reale (spesso
piu' stretto dell'1%), quindi il win rate implicito di breakeven sale
parecchio sopra 1% di reward. Nessuna regressione sul comportamento di
default (entrambi i parametri opt-in).

**3. Ipotesi di confluenza**: l'utente ha proposto che piu' trigger
strutturali indipendenti (BUD, terzo tocco, prossimita' al massimo/minimo
di ieri, prossimita' al massimo/minimo di oggi) allineati sullo stesso
livello dovrebbero rendere il trade piu' affidabile — non un gate
rigido ma un punteggio di confluenza. Prima di codificarlo come filtro,
misurato empiricamente: nuovo `log_confluence=True` in `BUDStrategy`
registra (senza influenzare l'ingresso) quanti di questi fattori sono
veri per ogni trigger, esposto via `confluence_log` (property combinata
su `BUDBidirectionalStrategy`). Nota implementativa: il "massimo di oggi"
usato per il confronto e' quello ANTECEDENTE alla barra di rottura stessa
(snapshot preso prima di aggiornare il massimo del giorno con la barra
corrente) — altrimenti il check sarebbe quasi tautologico ogni volta che
la barra di rottura e' anche il nuovo massimo di giornata.

**Risultato: l'ipotesi NON e' supportata dai dati.** Su BTC/USDT 1h
(2017-2019 e 2024-oggi), i trade SENZA alcuna conferma extra (confluenza
0) vanno meglio o alla pari di quelli con piu' conferme; sul campione
recente (227 trade, il piu' affidabile) avere tutti e 3 i fattori allineati
e' la categoria PEGGIORE (28.9% win rate, pnl -264) contro il 44.7%/+33
della categoria senza conferme. Ogni singolo fattore preso isolatamente
(terzo tocco, prossimita' ieri, prossimita' oggi) correla con risultati
peggiori del baseline "nessuna conferma" su entrambi i periodi, tranne
`today_extreme` che e' il migliore sul periodo vecchio (+109) ma il
peggiore su quello recente (-614) — la stessa inconsistenza tra periodi
gia' vista piu' volte in questa sessione con altri filtri. Possibili
letture, nessuna verificata: (a) la "vicinanza" e' misurata nel modo
sbagliato (tolleranza/timing), (b) l'edge su BTC 1h e' troppo debole
ovunque perche' il segnale emerga dal rumore, (c) l'ipotesi vale per
setup piu' selettivi di quanto il rilevamento BUD a candele riesca a
catturare meccanicamente. Da riverificare su altri asset/timeframe prima
di scartarla definitivamente.

## Runner disponibili in journal/

- `run_journal_backtest.py` / `run_journal_live.py` — journal generico con
  EMACrossStrategy (esempio, non BUD)
- `run_bud_backtest.py` — BUD solo long, su BTC
- `run_bud_bidirectional_backtest.py --dataset {short,full,5m,30m}` — BUD
  bidirezionale su BTC, vari timeframe/periodi
- `run_bud_multi_asset.py --asset {gold,nasdaq100,crudeoil} --tf {1h,4h}` — BUD
  bidirezionale + filtro trend su altri asset
