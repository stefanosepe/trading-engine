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

1. **Affinare la logica di TP a swing high** prima di renderla default: idee
   dagli screenshot da provare — estensione oltre il primo livello quando il
   momentum e' forte, uscite parziali/scalate. Il floor minimo in R e' stato
   implementato (`swing_tp_min_r`) ma da solo non basta a rendere positivo
   l'EV al netto dei costi
2. **Modellare "Bud Fintato"** (tolleranza a un primo falso breakout prima
   del trigger valido) — da valutare se estendere `ThirdTouchDetector` o
   scrivere un meccanismo dedicato
3. Un vero parameter sweep (multi-asset, multi-periodo) su
   `bud_lookback_min`/`appoggio_max_candles`/`bud_expansion_mult` invece di
   un singolo A/B su BTC — il tentativo fatto in questo giro non ha dato
   segnale pulito
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
```

## Runner disponibili in journal/

- `run_journal_backtest.py` / `run_journal_live.py` — journal generico con
  EMACrossStrategy (esempio, non BUD)
- `run_bud_backtest.py` — BUD solo long, su BTC
- `run_bud_bidirectional_backtest.py --dataset {short,full,5m,30m}` — BUD
  bidirezionale su BTC, vari timeframe/periodi
- `run_bud_multi_asset.py --asset {gold,nasdaq100,crudeoil} --tf {1h,4h}` — BUD
  bidirezionale + filtro trend su altri asset
