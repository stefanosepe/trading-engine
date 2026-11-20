"""Test dei componenti core: sizing a rischio fisso, risoluzione TP/SL del
PaperJournalBroker e simmetria long/short della strategia bidirezionale."""
from datetime import datetime

import pytest

from broker.paper_journal_broker import PaperJournalBroker
from core.events import MarketEvent, OrderDirection, SignalEvent, SignalType
from risk.manager import FixedRiskPerTradeManager
from strategies.bud_bidirectional import BUDBidirectionalStrategy

T0 = datetime(2026, 1, 1)


def bar(high, low, open_=None, close=None, symbol="BTC/USDT"):
    open_ = open_ if open_ is not None else (high + low) / 2
    close = close if close is not None else (high + low) / 2
    return MarketEvent(symbol, T0, open_, high, low, close, 1.0)


# --- FixedRiskPerTradeManager -------------------------------------------------

def test_long_size_matches_fixed_risk():
    rm = FixedRiskPerTradeManager(risk_per_trade=10, tp_r_multiple=2.0)
    signal = SignalEvent("BTC/USDT", T0, SignalType.LONG, stop_price=95)
    order = rm.size_order(signal, current_price=100, equity=10_000)
    assert order.direction == OrderDirection.BUY
    assert order.quantity == pytest.approx(2.0)        # 10 / (100 - 95)
    assert order.take_profit == pytest.approx(110)     # 2R sopra l'entrata


def test_short_size_matches_fixed_risk():
    rm = FixedRiskPerTradeManager(risk_per_trade=10, tp_r_multiple=2.0)
    signal = SignalEvent("BTC/USDT", T0, SignalType.SHORT, stop_price=105)
    order = rm.size_order(signal, current_price=100, equity=10_000)
    assert order.direction == OrderDirection.SELL
    assert order.quantity == pytest.approx(2.0)
    assert order.take_profit == pytest.approx(90)


@pytest.mark.parametrize("stop", [None, 100, 101])
def test_order_rejected_without_valid_stop(stop):
    rm = FixedRiskPerTradeManager(risk_per_trade=10)
    signal = SignalEvent("BTC/USDT", T0, SignalType.LONG, stop_price=stop)
    assert rm.size_order(signal, current_price=100, equity=10_000) is None


# --- PaperJournalBroker -------------------------------------------------------

def open_long(broker, entry=100, sl=95, tp=110):
    rm = FixedRiskPerTradeManager(risk_per_trade=10)
    broker.update_market_price("BTC/USDT", entry)
    signal = SignalEvent("BTC/USDT", T0, SignalType.LONG, stop_price=sl,
                         take_profit_price=tp)
    broker.execute_order(rm.size_order(signal, entry, broker.get_equity()))


def test_take_profit_closes_trade_with_gain():
    broker = PaperJournalBroker()
    open_long(broker)
    broker.check_pending(bar(high=111, low=99))
    trade = broker.trade_log()[0]
    assert trade["outcome"] == "TP"
    assert trade["pnl"] == pytest.approx(20)           # +2R con rischio 10
    assert not broker.has_open_position("BTC/USDT")


def test_stop_loss_wins_when_both_levels_touched():
    """Ipotesi conservativa documentata: se la barra tocca TP e SL, vince lo SL."""
    broker = PaperJournalBroker()
    open_long(broker)
    broker.check_pending(bar(high=115, low=90))
    trade = broker.trade_log()[0]
    assert trade["outcome"] == "SL"
    assert trade["pnl"] == pytest.approx(-10)


def test_trade_stays_open_inside_range():
    broker = PaperJournalBroker()
    open_long(broker)
    assert broker.check_pending(bar(high=105, low=97)) == []
    assert broker.has_open_position("BTC/USDT")


# --- Simmetria long/short -----------------------------------------------------

def test_mirroring_is_an_involution():
    original = bar(high=110, low=90, open_=95, close=105)
    mirrored = BUDBidirectionalStrategy._mirror_market_event(original)
    assert (mirrored.high, mirrored.low) == (-90, -110)
    back = BUDBidirectionalStrategy._mirror_market_event(mirrored)
    assert (back.open, back.high, back.low, back.close) == (95, 110, 90, 105)


def test_unmirrored_signal_is_short_with_flipped_levels():
    mirrored_long = SignalEvent("BTC/USDT", T0, SignalType.LONG,
                                stop_price=-105, take_profit_price=-90)
    short = BUDBidirectionalStrategy._unmirror_signal(mirrored_long)
    assert short.signal_type == SignalType.SHORT
    assert (short.stop_price, short.take_profit_price) == (105, 90)
