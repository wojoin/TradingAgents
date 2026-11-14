"""Market dispatch for the data reads that do not go through the tool router.

Settlement, the verified market snapshot and the instrument identity read
prices and profiles directly. A China A-share stock reads them from AKShare,
like its tools do, so the decision is settled on the same forward-adjusted bars
the analysts saw; Yahoo serves everything else, and is the fallback when AKShare
cannot answer.
"""

from __future__ import annotations

import logging

import pandas as pd

from tradingagents.dataflows.errors import VendorError
from tradingagents.dataflows.symbols import a_share_code, exchange_prefix
from tradingagents.dataflows.vendors.akshare import (
    fundamentals as akshare_fundamentals,
    prices as akshare_prices,
)
from tradingagents.dataflows.vendors.yahoo import snapshot as yahoo_snapshot
from tradingagents.dataflows.vendors.yahoo.fundamentals import (
    get_company_profile as yahoo_company_profile,
)
from tradingagents.dataflows.vendors.yahoo.market import get_closes as yahoo_closes

logger = logging.getLogger(__name__)

_EXCHANGES = {"SH": "Shanghai Stock Exchange", "SZ": "Shenzhen Stock Exchange", "BJ": "Beijing Stock Exchange"}


def get_closes(symbol: str, start_date: str, end_date: str) -> pd.Series:
    """Daily closes from ``start_date`` up to, not including, ``end_date``."""
    if a_share_code(symbol):
        try:
            return akshare_prices.get_closes(symbol, start_date, end_date)
        except VendorError as e:
            logger.warning("AKShare closes unavailable for %s (%s); trying Yahoo", symbol, e)
    return yahoo_closes(symbol, start_date, end_date)


def build_verified_market_snapshot(symbol: str, as_of_date: str, look_back_days: int = 30) -> str:
    """The ground-truth OHLCV and indicator snapshot, from the bars the tools use."""
    if a_share_code(symbol):
        try:
            return yahoo_snapshot.build_verified_market_snapshot(
                symbol, as_of_date, look_back_days, loader=akshare_prices.load_ohlcv)
        except VendorError as e:
            logger.warning("AKShare bars unavailable for the %s snapshot (%s); trying Yahoo", symbol, e)
            try:
                return yahoo_snapshot.build_verified_market_snapshot(symbol, as_of_date, look_back_days)
            except VendorError:
                raise e from None
    return yahoo_snapshot.build_verified_market_snapshot(symbol, as_of_date, look_back_days)


def get_company_profile(ticker: str) -> dict:
    """Today's name, sector and industry, in Yahoo's ``info`` keys.

    An A-share stock is named from the local Shenwan tables (申万一级 as the
    sector, 申万二级 as the industry), with no request; Yahoo otherwise.
    """
    if code := a_share_code(ticker):
        local = akshare_fundamentals.local_profile(code)
        if local.get("name"):
            profile = {"longName": local["name"], "exchange": _EXCHANGES[exchange_prefix(code)],
                       "quoteType": "EQUITY"}
            if "sw1" in local:
                profile["sector"] = local["sw1"]
            if "sw2" in local:
                profile["industry"] = local["sw2"]
            return profile
    return yahoo_company_profile(ticker)
