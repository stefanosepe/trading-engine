"""
PaperJournalBroker: il "papertrading su carta vera" che avevi chiesto.

Non si connette a nessun broker reale. Quando riceve un OrderEvent con
stop_loss/take_profit, apre un trade virtuale e lo tiene in sospeso.
Ad ogni nuova barra di mercato (via check_pending, chiamato dall'Engine)
controlla se il prezzo ha toccato TP o SL usando high/low della barra, e
se si' chiude il trade registrando l'esito.

Alla fine espone le statistiche che interessano a te: quanti trade,
percentuale di successo (win rate), R medio ottenuto.

LIMITE IMPORTANTE da tenere a mente: se in una singola barra vengono
toccati SIA il TP che lo SL (barra molto volatile), non possiamo sapere
con certezza quale sia stato colpito per primo solo da OHLC. Questo
broker adotta l'ipotesi conservativa: assume che lo SL sia stato toccato
per primo (worst case). Su timeframe piu' bassi (es. 1m) il problema si
riduce parecchio. Se serve precisione assoluta, l'alternativa e' usare
un feed di dati tick-by-tick invece che a barre.
"""
from dataclasses import dataclass, field

from core.events import FillEvent, OrderDirection, OrderEvent
from broker.base import Broker


@dataclass
class _OpenTrade:
    symbol: str
    source: str
    direction: OrderDirection
    quantity: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    opened_at: object
    entry_commission: float = 0.0


class PaperJournalBroker(Broker):
    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.0,
        slippage_pct: float = 0.0,
    ):
        """
        commission_pct: commissione per lato come frazione del nozionale
            (es. 0.001 = 0.1% sia all'apertura che alla chiusura). Default 0
            per compatibilita' con i risultati storici, ma i backtest "seri"
            dovrebbero passare un valore realistico.
        slippage_pct: peggioramento del prezzo di fill come frazione del
            prezzo, applicato SOLO ai fill di tipo market/stop (entrata e
            stop loss). Il take profit e' un ordine limit: fillato al prezzo
            esatto, senza slippage — al piu' il mercato lo salta a favore.
        """
        # capitale puramente virtuale: serve solo come base per il position
        # sizing (es. "rischia il 2% di 10k"), non rappresenta soldi reali
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        # chiave (symbol, source): permette a piu' strategie di avere
        # ciascuna un trade aperto sullo stesso simbolo senza sovrascriversi
        self._open_trades: dict[tuple[str, str], _OpenTrade] = {}
        self._closed_trades: list[dict] = []
        self._last_price: dict[str, float] = {}

    def update_market_price(self, symbol: str, price: float) -> None:
        self._last_price[symbol] = price

    def execute_order(self, order: OrderEvent) -> FillEvent:
        entry_price = self._last_price.get(order.symbol, order.limit_price)
        if entry_price is None:
            raise RuntimeError(f"Nessun prezzo disponibile per {order.symbol}")

        # slippage sull'entrata (ordine market): il fill peggiora nella
        # direzione del trade
        if self.slippage_pct:
            if order.direction == OrderDirection.BUY:
                entry_price *= 1 + self.slippage_pct
            else:
                entry_price *= 1 - self.slippage_pct

        entry_commission = abs(entry_price) * order.quantity * self.commission_pct

        source = order.source or "default"
        self._open_trades[(order.symbol, source)] = _OpenTrade(
            symbol=order.symbol,
            source=source,
            direction=order.direction,
            quantity=order.quantity,
            entry_price=entry_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=order.timestamp,
            entry_commission=entry_commission,
        )

        # fill "informativo": conferma l'apertura, non e' un'esecuzione reale
        return FillEvent(
            symbol=order.symbol,
            timestamp=order.timestamp,
            direction=order.direction,
            quantity=order.quantity,
            fill_price=entry_price,
            commission=entry_commission,
            source=source,
        )

    def check_pending(self, market_event) -> list[FillEvent]:
        symbol = market_event.symbol
        high, low = market_event.high, market_event.low
        fills = []

        # tutte le strategie con un trade aperto su questo simbolo, risolte
        # indipendentemente l'una dall'altra
        keys_for_symbol = [k for k in self._open_trades if k[0] == symbol]

        for key in keys_for_symbol:
            trade = self._open_trades[key]

            hit_sl = trade.stop_loss is not None and (
                (trade.direction == OrderDirection.BUY and low <= trade.stop_loss)
                or (trade.direction == OrderDirection.SELL and high >= trade.stop_loss)
            )
            hit_tp = trade.take_profit is not None and (
                (trade.direction == OrderDirection.BUY and high >= trade.take_profit)
                or (trade.direction == OrderDirection.SELL and low <= trade.take_profit)
            )
            if not hit_sl and not hit_tp:
                continue

            # ipotesi conservativa se toccati entrambi nella stessa barra: vince lo SL
            outcome = "SL" if hit_sl else "TP"
            exit_price = trade.stop_loss if hit_sl else trade.take_profit

            # slippage solo sullo stop (ordine stop/market): il TP e' un limit,
            # fillato al prezzo esatto
            if self.slippage_pct and hit_sl:
                if trade.direction == OrderDirection.BUY:
                    exit_price *= 1 - self.slippage_pct
                else:
                    exit_price *= 1 + self.slippage_pct

            exit_commission = abs(exit_price) * trade.quantity * self.commission_pct

            pnl_per_unit = (
                exit_price - trade.entry_price
                if trade.direction == OrderDirection.BUY
                else trade.entry_price - exit_price
            )
            pnl = pnl_per_unit * trade.quantity - trade.entry_commission - exit_commission
            won = pnl > 0

            self._closed_trades.append(
                {
                    "symbol": symbol,
                    "source": trade.source,
                    "direction": trade.direction.value,
                    "entry_price": trade.entry_price,
                    "exit_price": exit_price,
                    "outcome": outcome,
                    "pnl": pnl,
                    "won": won,
                    "opened_at": trade.opened_at,
                    "closed_at": market_event.timestamp,
                }
            )
            del self._open_trades[key]

            exit_direction = (
                OrderDirection.SELL
                if trade.direction == OrderDirection.BUY
                else OrderDirection.BUY
            )
            fills.append(
                FillEvent(
                    symbol=symbol,
                    timestamp=market_event.timestamp,
                    direction=exit_direction,
                    quantity=trade.quantity,
                    fill_price=exit_price,
                    commission=exit_commission,
                    source=trade.source,
                )
            )

        return fills

    def get_equity(self) -> float:
        # equity virtuale: capitale iniziale + PnL chiusi (non e' un vero conto)
        return self.initial_capital + sum(t["pnl"] for t in self._closed_trades)

    def has_open_position(self, symbol: str, source: str | None = None) -> bool:
        return (symbol, source or "default") in self._open_trades

    def stats(self, source: str | None = None) -> dict:
        """Se source e' specificato, filtra le statistiche per quella sola
        strategia (utile quando piu' strategie girano insieme)."""
        trades = self._closed_trades
        if source is not None:
            trades = [t for t in trades if t["source"] == source]

        n = len(trades)
        open_trades = (
            len(self._open_trades)
            if source is None
            else sum(1 for k in self._open_trades if k[1] == source)
        )
        if n == 0:
            return {"n_trades": 0, "win_rate_pct": None, "open_trades": open_trades}

        wins = sum(1 for t in trades if t["won"])
        total_pnl = sum(t["pnl"] for t in trades)
        avg_win = sum(t["pnl"] for t in trades if t["won"]) / wins if wins else 0.0
        losses = n - wins
        avg_loss = sum(t["pnl"] for t in trades if not t["won"]) / losses if losses else 0.0

        return {
            "n_trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / n * 100, 2),
            "total_pnl": round(total_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "open_trades": open_trades,
        }

    def trade_log(self, source: str | None = None) -> list[dict]:
        if source is None:
            return list(self._closed_trades)
        return [t for t in self._closed_trades if t["source"] == source]
