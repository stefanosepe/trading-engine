"""
ThirdTouchDetector — rileva livelli di prezzo toccati e rigettati piu'
volte, con l'obiettivo di segnalare quando ci si sta avvicinando a un
terzo tocco (dove un setup BUD nelle vicinanze diventerebbe piu' interessante).

NON e' una Strategy: non genera SignalEvent, non ha un proprio ciclo di
vita di trade. E' un componente informativo, pensato per essere passato
come filtro di confluenza a BUDStrategy in futuro (integrazione NON
ancora applicata — questo file resta a se' stante per ora, come
richiesto: "implementa ma non applicare").

Pensato per timeframe alti (4h, 1d, weekly): su timeframe bassi il rumore
genera troppi pivot poco significativi.

Definizione di "tocco" (dalla spiegazione dell'utente):
- il prezzo raggiunge un livello (con un piccolo buffer di tolleranza)
- poi si ritira ("raccoglie liquidita'") — quindi il tocco e' un pivot
  vero e proprio, non solo un prezzo sfiorato di striscio
- risale e viene rigettato di nuovo dallo stesso livello (secondo tocco)
- quando il prezzo si riavvicina una terza volta, e' il momento in cui
  un BUD nelle vicinanze anticiperebbe il terzo tocco

Il filtro di trend (mai controtrend) resta di competenza di BUDStrategy,
non duplicato qui.
"""
from dataclasses import dataclass, field


@dataclass
class _Pivot:
    timestamp: object
    price: float


@dataclass
class _Level:
    price: float  # prezzo di riferimento (media dei tocchi che lo compongono)
    touches: list = field(default_factory=list)  # list[_Pivot]

    def add_touch(self, pivot: _Pivot) -> None:
        self.touches.append(pivot)
        self.price = sum(t.price for t in self.touches) / len(self.touches)


@dataclass
class ThirdTouchInfo:
    symbol: str
    timestamp: object
    level_price: float
    num_touches: int
    approaching_third: bool       # 2 tocchi confermati, prezzo si sta riavvicinando
    third_touch_confirmed: bool   # il pivot appena confermato E' il terzo tocco


class ThirdTouchDetector:
    def __init__(
        self,
        direction: str = "resistance",  # "resistance" (rigetti dall'alto) | "support" (dal basso)
        pivot_lookback: int = 3,
        tolerance_pct: float = 0.005,
        approach_pct: float = 0.01,
        max_level_age_bars: int = 500,
        max_active_levels: int = 5,
    ):
        """
        pivot_lookback: candele da ciascun lato per confermare un pivot
            (swing high/low classico). NB: introduce un ritardo di
            `pivot_lookback` barre prima che un tocco venga confermato —
            e' l'analogo "costo" della definizione a pivot, non un bug.
        tolerance_pct: quanto vicini devono essere due pivot per essere
            considerati lo stesso livello (es. 0.005 = 0.5%)
        approach_pct: entro quale distanza dal livello si considera il
            prezzo "in avvicinamento" al tocco successivo
        max_level_age_bars: TODO non ancora implementato in questa versione
            (i livelli vengono scartati solo per FIFO via max_active_levels,
            non per eta'). Parametro tenuto per l'interfaccia futura.
        """
        if direction not in ("resistance", "support"):
            raise ValueError("direction deve essere 'resistance' o 'support'")
        self.direction = direction
        self.pivot_lookback = pivot_lookback
        self.tolerance_pct = tolerance_pct
        self.approach_pct = approach_pct
        self.max_level_age_bars = max_level_age_bars
        self.max_active_levels = max_active_levels

        self._buffer: dict[str, list] = {}
        self._levels: dict[str, list[_Level]] = {}
        self._bar_index: dict[str, int] = {}

    def reset(self) -> None:
        self._buffer.clear()
        self._levels.clear()
        self._bar_index.clear()

    # ------------------------------------------------------------------

    def on_market_event(self, event) -> ThirdTouchInfo | None:
        symbol = event.symbol
        buf = self._buffer.setdefault(symbol, [])
        buf.append(event)

        window = 2 * self.pivot_lookback + 1
        if len(buf) > window:
            buf.pop(0)

        self._bar_index[symbol] = self._bar_index.get(symbol, 0) + 1

        confirmed_pivot = None
        if len(buf) == window:
            confirmed_pivot = self._check_pivot(buf)

        third_touch_confirmed = False
        if confirmed_pivot is not None:
            third_touch_confirmed = self._register_touch(symbol, confirmed_pivot)

        return self._check_approach(symbol, event, third_touch_confirmed)

    # ------------------------------------------------------------------

    def _check_pivot(self, buf: list) -> _Pivot | None:
        center = buf[self.pivot_lookback]
        others = buf[: self.pivot_lookback] + buf[self.pivot_lookback + 1 :]

        if self.direction == "resistance":
            is_pivot = all(center.high >= c.high for c in others)
            price = center.high
        else:
            is_pivot = all(center.low <= c.low for c in others)
            price = center.low

        return _Pivot(timestamp=center.timestamp, price=price) if is_pivot else None

    def _register_touch(self, symbol: str, pivot: _Pivot) -> bool:
        """Aggancia il pivot a un livello esistente (entro tolleranza) o ne
        crea uno nuovo. Ritorna True se questo tocco porta il livello a 3."""
        levels = self._levels.setdefault(symbol, [])

        for level in levels:
            # abs() al denominatore: sul lato short (via BUDBidirectionalStrategy)
            # i prezzi arrivano ribaltati/negativi e senza abs il confronto
            # percentuale sarebbe sempre vero (quoziente negativo)
            if abs(pivot.price - level.price) / abs(level.price) <= self.tolerance_pct:
                level.add_touch(pivot)
                return len(level.touches) == 3

        new_level = _Level(price=pivot.price, touches=[pivot])
        levels.append(new_level)
        if len(levels) > self.max_active_levels:
            levels.pop(0)  # scarta il piu' vecchio
        return False

    def _check_approach(
        self, symbol: str, event, third_touch_confirmed: bool
    ) -> ThirdTouchInfo | None:
        levels = self._levels.get(symbol, [])
        # livelli con esattamente 2 tocchi: candidati per un terzo imminente
        two_touch_levels = [lv for lv in levels if len(lv.touches) == 2]

        for level in two_touch_levels:
            distance_pct = abs(event.close - level.price) / abs(level.price)
            approaching = distance_pct <= self.approach_pct
            if self.direction == "resistance":
                approaching = approaching and event.close <= level.price
            else:
                approaching = approaching and event.close >= level.price

            if approaching:
                return ThirdTouchInfo(
                    symbol=symbol,
                    timestamp=event.timestamp,
                    level_price=level.price,
                    num_touches=2,
                    approaching_third=True,
                    third_touch_confirmed=False,
                )

        if third_touch_confirmed:
            # trova il livello appena portato a 3 tocchi per riportarlo
            for level in levels:
                if len(level.touches) == 3:
                    return ThirdTouchInfo(
                        symbol=symbol,
                        timestamp=event.timestamp,
                        level_price=level.price,
                        num_touches=3,
                        approaching_third=False,
                        third_touch_confirmed=True,
                    )

        return None
