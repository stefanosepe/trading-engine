"""
SwingLevelTracker — rileva swing high (pivot) confermati e li tiene come
livelli di resistenza "vivi" finche' il prezzo non li rompe in chiusura.

Nato dalla calibrazione su 661 screenshot reali di trade BUD (vedi
PROJECT_CONTEXT.md): il take profit osservato non e' quasi mai un multiplo R
fisso ne' un'EMA di timeframe superiore (mai osservata), ma quasi sempre il
prossimo swing high/resistenza visibile sullo stesso timeframe. Questo
componente risponde alla domanda "qual e' la prossima resistenza sopra il
prezzo corrente", usata da BUDStrategy come target di take profit.

Definizione di pivot high: una candela il cui high e' >= agli high di
`pivot_lookback` candele prima e dopo (swing high classico, stesso criterio
gia' usato da ThirdTouchDetector). Introduce un ritardo di `pivot_lookback`
barre prima che un pivot venga confermato — e' il costo della definizione a
pivot, non un bug.

Un livello resta "vivo" (candidato come target) finche' il prezzo non chiude
sopra di esso: a quel punto la resistenza e' rotta e smette di avere senso
come target di take profit.
"""


class SwingLevelTracker:
    def __init__(self, pivot_lookback: int = 3, max_active_levels: int = 20):
        self.pivot_lookback = pivot_lookback
        self.max_active_levels = max_active_levels
        self._buffer: dict[str, list] = {}
        self._levels: dict[str, list[float]] = {}

    def reset(self) -> None:
        self._buffer.clear()
        self._levels.clear()

    # ------------------------------------------------------------------

    def on_market_event(self, event) -> None:
        symbol = event.symbol
        buf = self._buffer.setdefault(symbol, [])
        buf.append(event)

        window = 2 * self.pivot_lookback + 1
        if len(buf) > window:
            buf.pop(0)

        levels = self._levels.setdefault(symbol, [])
        # un livello smette di essere resistenza quando il prezzo chiude sopra
        levels[:] = [lv for lv in levels if event.close < lv]

        if len(buf) == window:
            center = buf[self.pivot_lookback]
            others = buf[: self.pivot_lookback] + buf[self.pivot_lookback + 1 :]
            if all(center.high >= c.high for c in others) and center.high not in levels:
                levels.append(center.high)
                if len(levels) > self.max_active_levels:
                    levels.pop(0)  # scarta il piu' vecchio

    def next_resistance_above(self, symbol: str, price: float) -> float | None:
        """Il livello vivo piu' vicino sopra `price`, o None se nessuno registrato."""
        levels = [lv for lv in self._levels.get(symbol, []) if lv > price]
        return min(levels) if levels else None
