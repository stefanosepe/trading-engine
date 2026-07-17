"""
Strategia di esempio: incrocio di due medie mobili esponenziali (EMA).

Specifica formale (quella che avevamo detto di scrivere PRIMA di codificare):
- EMA veloce periodo `fast_period`, EMA lenta periodo `slow_period`
- Entrata LONG: quando EMA veloce incrocia sopra la EMA lenta
- Entrata SHORT: quando EMA veloce incrocia sotto la EMA lenta (disattivabile)
- Uscita: quando avviene l'incrocio opposto (nessun altro stop qui:
  lo stop-loss/take-profit è responsabilità del RiskManager, non della
  Strategy, per mantenere la separazione delle responsabilità)
- Timeframe: dipende dai dati passati in input (agnostico qui)
"""
from core.events import MarketEvent, SignalEvent, SignalType
from strategies.base import Strategy


class EMACrossStrategy(Strategy):
    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        allow_short: bool = False,
    ):
        if fast_period >= slow_period:
            raise ValueError("fast_period deve essere minore di slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.allow_short = allow_short

        self._fast_alpha = 2 / (fast_period + 1)
        self._slow_alpha = 2 / (slow_period + 1)

        # stato interno per simbolo
        self._fast_ema: dict[str, float] = {}
        self._slow_ema: dict[str, float] = {}
        self._prev_diff: dict[str, float] = {}  # fast - slow al tick precedente
        self._position: dict[str, SignalType | None] = {}
        self._bars_seen: dict[str, int] = {}

    def reset(self) -> None:
        self._fast_ema.clear()
        self._slow_ema.clear()
        self._prev_diff.clear()
        self._position.clear()
        self._bars_seen.clear()

    def on_market_event(self, event: MarketEvent) -> SignalEvent | None:
        symbol = event.symbol
        price = event.close

        # inizializzazione EMA alla prima barra vista per il simbolo
        if symbol not in self._fast_ema:
            self._fast_ema[symbol] = price
            self._slow_ema[symbol] = price
            self._prev_diff[symbol] = 0.0
            self._position[symbol] = None
            self._bars_seen[symbol] = 1
            return None

        self._bars_seen[symbol] += 1

        self._fast_ema[symbol] = (
            price * self._fast_alpha + self._fast_ema[symbol] * (1 - self._fast_alpha)
        )
        self._slow_ema[symbol] = (
            price * self._slow_alpha + self._slow_ema[symbol] * (1 - self._slow_alpha)
        )

        diff = self._fast_ema[symbol] - self._slow_ema[symbol]
        prev_diff = self._prev_diff[symbol]
        self._prev_diff[symbol] = diff

        # serve un minimo di barre prima che le EMA siano "affidabili"
        if self._bars_seen[symbol] < self.slow_period:
            return None

        signal = None

        # incrocio verso l'alto: prev_diff <= 0 e diff > 0
        if prev_diff <= 0 < diff:
            if self._position.get(symbol) != SignalType.LONG:
                self._position[symbol] = SignalType.LONG
                signal = SignalEvent(symbol, event.timestamp, SignalType.LONG)

        # incrocio verso il basso: prev_diff >= 0 e diff < 0
        elif prev_diff >= 0 > diff:
            if self.allow_short:
                if self._position.get(symbol) != SignalType.SHORT:
                    self._position[symbol] = SignalType.SHORT
                    signal = SignalEvent(symbol, event.timestamp, SignalType.SHORT)
            else:
                if self._position.get(symbol) == SignalType.LONG:
                    self._position[symbol] = None
                    signal = SignalEvent(symbol, event.timestamp, SignalType.EXIT)

        return signal
