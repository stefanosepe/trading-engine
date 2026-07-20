"""
Strategia BUD (dal nome dato dall'utente).

Macchina a stati per simbolo, con 3 fasi:

  SCANNING  -> rileva la sequenza "in viagra" + candela di espansione (BUD)
  APPOGGIO  -> il prezzo tiene sopra EMA_stop; cerca la candela di innesco
               (range contratto, sfiora l'EMA senza chiuderci sotto)
  (entrata) -> rottura del trigger (innesco o, in fallback, BUD stesso)

Alla rottura emette un SignalEvent LONG con stop_price e take_profit_price
gia' calcolati dalla struttura del pattern (EMA_stop - buffer ATR; TP a
multiplo R, salvo diversa configurazione).

SEMPLIFICAZIONI CONSAPEVOLI rispetto alla descrizione originale (da
affinare in iterazioni successive, segnalate esplicitamente):
- Il Take Profit "prima EMA sul timeframe superiore" ipotizzato inizialmente
  NON e' mai stato confermato dalla calibrazione su 661 screenshot reali
  (vedi PROJECT_CONTEXT.md): in nessuno screenshot il TP era un'EMA di
  timeframe superiore. Il pattern osservato e' invece "prossimo swing
  high/resistenza sullo stesso timeframe", modellato qui da
  SwingLevelTracker. Se nessun livello e' disponibile (fase iniziale della
  serie storica), si ricade sul multiplo R (tp_r_multiple) come fallback.
- La conferma via order book non e' modellata (i dati OHLC non la
  contengono): il rilevamento si basa solo su struttura delle candele.
- Solo lato LONG (la logica descritta era per un contesto rialzista;
  facile da speculare in futuro se serve anche lo short).
- L'entrata viene valutata alla chiusura della barra di rottura, non
  intrabar: e' la stessa approssimazione gia' presente nel resto
  dell'infrastruttura (BacktestBroker fillava a "close").
- Pattern osservati ma NON implementati (vedi PROJECT_CONTEXT.md): "Bud
  Fintato" (tolleranza a un primo falso breakout prima del trigger valido)
  e gestione dinamica del trade (stop a breakeven, TP scalato, ingressi
  piramidati) — richiedono modifiche piu' ampie all'infrastruttura
  (Engine/Broker gestiscono oggi un solo TP/SL fissato all'apertura).
"""
from dataclasses import dataclass, field

from core.events import MarketEvent, SignalEvent, SignalType
from strategies.base import Strategy
from strategies.swing_levels import SwingLevelTracker
from strategies.third_touch import ThirdTouchDetector


@dataclass
class _Candle:
    timestamp: object
    open: float
    high: float
    low: float
    close: float

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class _SymbolState:
    phase: str = "SCANNING"  # SCANNING | APPOGGIO
    seq_candles: list = field(default_factory=list)     # sequenza "in viagra"
    bud_high: float | None = None
    appoggio_candles: list = field(default_factory=list)
    trigger_price: float | None = None                  # prezzo di rottura da superare
    stop_ema_at_setup: float | None = None               # EMA_stop al momento del setup
    is_fallback_trigger: bool = False                    # True se il trigger e' bud_high


class BUDStrategy(Strategy):
    def __init__(
        self,
        ema_fast_period: int = 5,
        ema_stop_period: int = 10,
        ema_trend_period: int | None = 60,
        bud_lookback_min: int = 3,
        bud_expansion_mult: float = 1.5,
        appoggio_min_candles: int = 1,
        appoggio_max_candles: int = 6,
        innesco_contraction_ratio: float = 0.5,
        atr_period: int = 14,
        stop_buffer_atr_mult: float = 0.25,
        tp_r_multiple: float = 2.0,
        use_swing_tp: bool = False,
        swing_pivot_lookback: int = 3,
        swing_max_active_levels: int = 20,
        require_third_touch: bool = False,
        third_touch_pivot_lookback: int = 3,
        third_touch_tolerance_pct: float = 0.005,
        third_touch_approach_pct: float = 0.01,
        third_touch_lookback_bars: int = 20,
    ):
        """
        ema_trend_period: se valorizzata, aggiunge il filtro di trend — si
        entra LONG solo se il prezzo (alla rottura) e' sopra questa EMA,
        mai controtrend. None = filtro disattivato. Valore tipico: 60 per
        crypto, 50 per azionario/indici/commodity.

        bud_lookback_min / appoggio_max_candles: gli screenshot suggerivano
        valori piu' bassi/ampi (i BUD reali sono spesso 1-2 candele prima
        dello spike, gli appoggi arrivano spesso a 8-10+ candele) ma un test
        A/B su BTC/USDT 1h (2017-2019 e un sotto-periodo 2019) ha dato
        risultati incoerenti/peggiorativi cambiando questi default (vedi
        PROJECT_CONTEXT.md) — quindi restano ai valori originali, gia'
        validati dai backtest storici. Restano parametri liberi da esplorare
        con un vero parameter sweep, non solo impressioni qualitative dagli
        screenshot.

        use_swing_tp: se True, il take profit e' il prossimo swing high non
        ancora rotto sopra il prezzo d'entrata (SwingLevelTracker) invece del
        multiplo R fisso — e' il comportamento osservato quasi ovunque negli
        screenshot reali (mai un multiplo R fisso, mai un'EMA di timeframe
        superiore). PERO' un backtest su BTC/USDT 1h mostra che la versione
        "prendi sempre il livello piu' vicino" alza il win rate (fino al
        63% su alcuni periodi) ma abbassa il PnL netto rispetto al multiplo
        2R fisso, perche' taglia corto i trade migliori — gli screenshot
        mostrano spesso uscite scalate o target estesi oltre il primo
        livello, comportamento non modellato qui. Default a False (fallback
        sicuro sul multiplo R) finche' non si affina questa logica (vedi
        PROJECT_CONTEXT.md); il meccanismo resta disponibile e testato per
        chi vuole sperimentarci.

        require_third_touch: se True, l'entrata BUD e' un filtro OBBLIGATORIO
        — si entra SOLO se il trigger di rottura e' vicino a un livello che
        ha gia' 2 tocchi confermati (in avvicinamento al terzo) o appena
        arrivato al terzo, secondo ThirdTouchDetector. Nessuna confluenza =
        nessun segnale, anche se il resto del pattern BUD e' valido.

        Nota sul lato short (via BUDBidirectionalStrategy): sia il detector
        del terzo tocco sia SwingLevelTracker usano sempre lo spazio dati
        "long"/resistenza — per l'istanza "short", che riceve dati gia'
        ribaltati dal wrapper, questo diventa automaticamente supporto nello
        spazio reale, esattamente come per il resto della logica BUD.
        """
        self.ema_fast_period = ema_fast_period
        self.ema_stop_period = ema_stop_period
        self.ema_trend_period = ema_trend_period
        self.bud_lookback_min = bud_lookback_min
        self.bud_expansion_mult = bud_expansion_mult
        self.appoggio_min_candles = appoggio_min_candles
        self.appoggio_max_candles = appoggio_max_candles
        self.innesco_contraction_ratio = innesco_contraction_ratio
        self.atr_period = atr_period
        self.stop_buffer_atr_mult = stop_buffer_atr_mult
        self.tp_r_multiple = tp_r_multiple
        self.use_swing_tp = use_swing_tp
        self.require_third_touch = require_third_touch
        self.third_touch_lookback_bars = third_touch_lookback_bars
        self.third_touch_tolerance_pct = third_touch_tolerance_pct

        self._ema_fast_alpha = 2 / (ema_fast_period + 1)
        self._ema_stop_alpha = 2 / (ema_stop_period + 1)
        self._ema_trend_alpha = 2 / (ema_trend_period + 1) if ema_trend_period else None

        self._ema_fast: dict[str, float] = {}
        self._ema_stop: dict[str, float] = {}
        self._ema_trend: dict[str, float] = {}
        self._prev_close: dict[str, float] = {}
        self._atr: dict[str, float] = {}
        self._bars_seen: dict[str, int] = {}
        self._state: dict[str, _SymbolState] = {}

        self._third_touch = (
            ThirdTouchDetector(
                direction="resistance",
                pivot_lookback=third_touch_pivot_lookback,
                tolerance_pct=third_touch_tolerance_pct,
                approach_pct=third_touch_approach_pct,
            )
            if require_third_touch
            else None
        )
        self._swing_tracker = (
            SwingLevelTracker(
                pivot_lookback=swing_pivot_lookback,
                max_active_levels=swing_max_active_levels,
            )
            if use_swing_tp
            else None
        )
        # ultima confluenza vista per simbolo: (livello_prezzo, indice_barra)
        self._last_confluence: dict[str, tuple[float, int]] = {}

    def reset(self) -> None:
        self._ema_fast.clear()
        self._ema_stop.clear()
        self._ema_trend.clear()
        self._prev_close.clear()
        self._atr.clear()
        self._bars_seen.clear()
        self._state.clear()
        self._last_confluence.clear()
        if self._third_touch is not None:
            self._third_touch.reset()
        if self._swing_tracker is not None:
            self._swing_tracker.reset()

    # ------------------------------------------------------------------

    def on_market_event(self, event: MarketEvent) -> SignalEvent | None:
        symbol = event.symbol
        candle = _Candle(event.timestamp, event.open, event.high, event.low, event.close)

        self._update_indicators(symbol, candle)
        if self._swing_tracker is not None:
            self._swing_tracker.on_market_event(event)

        min_bars = max(self.ema_stop_period, self.atr_period, self.ema_trend_period or 0) + 1
        self._bars_seen[symbol] = self._bars_seen.get(symbol, 0) + 1
        if self._bars_seen[symbol] < min_bars:
            return None  # indicatori non ancora affidabili

        if self._third_touch is not None:
            info = self._third_touch.on_market_event(event)
            if info is not None and (info.approaching_third or info.third_touch_confirmed):
                self._last_confluence[symbol] = (info.level_price, self._bars_seen[symbol])

        state = self._state.setdefault(symbol, _SymbolState())
        ema_fast = self._ema_fast[symbol]
        ema_stop = self._ema_stop[symbol]

        if state.phase == "SCANNING":
            self._scan_for_bud(state, candle, ema_fast)
            return None

        # phase == "APPOGGIO"
        return self._handle_appoggio(symbol, state, candle, ema_stop)

    # ------------------------------------------------------------------

    def _update_indicators(self, symbol: str, candle: _Candle) -> None:
        if symbol not in self._ema_fast:
            self._ema_fast[symbol] = candle.close
            self._ema_stop[symbol] = candle.close
            if self._ema_trend_alpha is not None:
                self._ema_trend[symbol] = candle.close
            self._prev_close[symbol] = candle.close
            self._atr[symbol] = candle.range
            return

        self._ema_fast[symbol] = (
            candle.close * self._ema_fast_alpha
            + self._ema_fast[symbol] * (1 - self._ema_fast_alpha)
        )
        self._ema_stop[symbol] = (
            candle.close * self._ema_stop_alpha
            + self._ema_stop[symbol] * (1 - self._ema_stop_alpha)
        )
        if self._ema_trend_alpha is not None:
            self._ema_trend[symbol] = (
                candle.close * self._ema_trend_alpha
                + self._ema_trend[symbol] * (1 - self._ema_trend_alpha)
            )

        true_range = max(
            candle.high - candle.low,
            abs(candle.high - self._prev_close[symbol]),
            abs(candle.low - self._prev_close[symbol]),
        )
        atr_alpha = 1 / self.atr_period
        self._atr[symbol] = true_range * atr_alpha + self._atr[symbol] * (1 - atr_alpha)
        self._prev_close[symbol] = candle.close

    # ------------------------------------------------------------------

    def _scan_for_bud(self, state: _SymbolState, candle: _Candle, ema_fast: float) -> None:
        qualifies = candle.is_green and candle.close > ema_fast

        if not qualifies:
            state.seq_candles = []
            return

        state.seq_candles.append(candle)

        if len(state.seq_candles) < self.bud_lookback_min:
            return

        prior = state.seq_candles[:-1]
        avg_prior_range = sum(c.range for c in prior) / len(prior) if prior else candle.range

        if avg_prior_range > 0 and candle.range >= self.bud_expansion_mult * avg_prior_range:
            # BUD rilevato: passa in fase di appoggio
            state.phase = "APPOGGIO"
            state.bud_high = candle.high
            state.appoggio_candles = []
            state.trigger_price = None
            state.stop_ema_at_setup = None
            state.is_fallback_trigger = False
            state.seq_candles = []

    # ------------------------------------------------------------------

    def _handle_appoggio(
        self, symbol: str, state: _SymbolState, candle: _Candle, ema_stop: float
    ) -> SignalEvent | None:
        # invalidazione: chiusura sotto l'EMA di stop rompe il supporto
        if candle.close < ema_stop:
            self._reset_to_scanning(state, candle)
            return None

        # controllo rottura, se un trigger e' gia' stato individuato
        if state.trigger_price is not None and candle.high >= state.trigger_price:
            return self._fire_entry(symbol, state, candle, ema_stop)

        state.appoggio_candles.append(candle)

        # individuazione della candela di innesco (range contratto, sfiora l'EMA)
        if state.trigger_price is None and len(state.appoggio_candles) >= 1:
            prior = state.appoggio_candles[:-1]
            if prior:
                avg_range = sum(c.range for c in prior) / len(prior)
                is_contracted = (
                    avg_range > 0 and candle.range <= self.innesco_contraction_ratio * avg_range
                )
                touches_ema = candle.low <= ema_stop * 1.001  # piccola tolleranza
                if is_contracted and touches_ema:
                    state.trigger_price = candle.high
                    state.stop_ema_at_setup = ema_stop
                    state.is_fallback_trigger = False

        # fallback: se scaduta la finestra di appoggio senza innesco, usa BUD come trigger
        if (
            state.trigger_price is None
            and len(state.appoggio_candles) >= self.appoggio_min_candles
            and len(state.appoggio_candles) >= self.appoggio_max_candles
        ):
            state.trigger_price = state.bud_high
            state.stop_ema_at_setup = ema_stop
            state.is_fallback_trigger = True

        # se anche col fallback il setup langue troppo a lungo, abbandona
        if len(state.appoggio_candles) > self.appoggio_max_candles * 2:
            self._reset_to_scanning(state, candle)

        return None

    # ------------------------------------------------------------------

    def _fire_entry(
        self, symbol: str, state: _SymbolState, candle: _Candle, ema_stop: float
    ) -> SignalEvent | None:
        # filtro di trend: mai controtrend. In questo spazio (anche per lo
        # short, che gira su dati ribaltati) "long" e' sempre la direzione
        # nativa della classe, quindi il controllo e' identico per entrambi.
        if self.ema_trend_period is not None:
            ema_trend = self._ema_trend[symbol]
            if candle.close <= ema_trend:
                self._reset_to_scanning(state, candle)
                return None

        entry_price = state.trigger_price

        # filtro terzo tocco: obbligatorio se richiesto, nessuna confluenza
        # recente e vicina al prezzo di entrata = niente segnale
        if self.require_third_touch and not self._has_third_touch_confluence(
            symbol, entry_price
        ):
            self._reset_to_scanning(state, candle)
            return None

        atr = self._atr[symbol]
        stop_price = (state.stop_ema_at_setup or ema_stop) - self.stop_buffer_atr_mult * atr

        take_profit_price = None
        if self._swing_tracker is not None:
            take_profit_price = self._swing_tracker.next_resistance_above(symbol, entry_price)
        # se nessun livello e' disponibile, take_profit_price resta None e il
        # RiskManager ricade sul multiplo tp_r_multiple (vedi FixedRiskPerTradeManager)

        signal = SignalEvent(
            symbol=symbol,
            timestamp=candle.timestamp,
            signal_type=SignalType.LONG,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

        self._reset_to_scanning(state, candle)
        return signal

    def _has_third_touch_confluence(self, symbol: str, entry_price: float) -> bool:
        confluence = self._last_confluence.get(symbol)
        if confluence is None:
            return False
        level_price, seen_at_bar = confluence
        if self._bars_seen[symbol] - seen_at_bar > self.third_touch_lookback_bars:
            return False  # confluenza vista troppo tempo fa, non piu' valida
        # "vicino" = entro un margine un po' piu' largo della tolleranza
        # di clustering del detector stesso (che e' molto stretta)
        proximity = self.third_touch_tolerance_pct * 3
        return abs(entry_price - level_price) / level_price <= proximity

    def _reset_to_scanning(self, state: _SymbolState, candle: _Candle) -> None:
        state.phase = "SCANNING"
        state.seq_candles = []
        state.bud_high = None
        state.appoggio_candles = []
        state.trigger_price = None
        state.stop_ema_at_setup = None
        state.is_fallback_trigger = False
