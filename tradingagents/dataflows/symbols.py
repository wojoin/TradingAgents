"""Symbol normalization for vendor calls, and ticker values safe to use in a path.

Yahoo Finance (the default vendor) uses specific ticker conventions that
differ from the broker / TradingView / MT5 style symbols users often type:

    user types        Yahoo wants       why
    ---------------   ---------------   -----------------------------------
    XAUUSD, XAUUSD+   GC=F              gold has no forex pair on Yahoo;
                                        it is quoted as a COMEX future
    EURUSD            EURUSD=X          spot forex pairs take a ``=X`` suffix
    BTCUSD            BTC-USD           crypto pairs use a ``-`` separator
    SPX500, US500     ^GSPC             index CFDs map to Yahoo index symbols
    09992.HK, 700.HK  9992.HK, 0700.HK  HK codes are zero-padded to 4 digits
    600519.SH         600519.SS         Yahoo spells Shanghai ``.SS``

Passing the raw broker symbol to Yahoo returns an empty result, which the
agents previously received as free text and could hallucinate a price
around (see issue #781). Centralizing the mapping here means every yfinance
entry point resolves symbols the same way, and new instruments are added by
appending a table row rather than editing call sites.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ISO-4217 codes common enough to appear in retail forex pairs. A bare
# six-letter symbol whose halves are BOTH in this set is treated as a spot
# forex pair and given Yahoo's ``=X`` suffix.
_FOREX_CURRENCIES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
        "CNY", "CNH", "HKD", "SGD", "SEK", "NOK", "DKK", "PLN",
        "MXN", "ZAR", "TRY", "INR", "KRW", "BRL", "RUB", "THB",
    }
)

# Crypto bases that brokers quote against USD without a separator.
_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX", "LINK"}
)

# Explicit aliases for instruments whose broker symbol does not map to a
# Yahoo symbol by rule. Metals/energy resolve to their front-month future;
# index CFD names resolve to the underlying Yahoo index symbol. Extend by
# adding rows — no call site changes required.
_ALIASES = {
    # Precious metals (spot names -> COMEX/NYMEX futures)
    "XAUUSD": "GC=F", "XAU": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    # Energy
    "WTICOUSD": "CL=F", "USOIL": "CL=F", "WTI": "CL=F",
    "BCOUSD": "BZ=F", "UKOIL": "BZ=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "XNGUSD": "NG=F",
    "COPPER": "HG=F", "XCUUSD": "HG=F",
    # Index CFDs -> Yahoo index symbols
    "SPX500": "^GSPC", "US500": "^GSPC", "SPX": "^GSPC",
    "NAS100": "^NDX", "US100": "^NDX", "USTEC": "^NDX",
    "US30": "^DJI", "DJI30": "^DJI", "WS30": "^DJI",
    "GER40": "^GDAXI", "GER30": "^GDAXI", "DE40": "^GDAXI",
    "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "HK50": "^HSI",
}

# HKEX codes as Yahoo spells them: the number zero-padded to 4 digits (#957).
_HK_CODE = re.compile(r"^(\d{1,5})\.HK$")

# China A-share stocks, in the forms brokers and data sites write them:
# ``600519``, ``600519.SH`` / ``.SS``, ``000001.SZ``, ``920001.BJ``, ``SH600519``.
_A_SHARE_SUFFIXED = re.compile(r"^(\d{6})\.(SH|SS|SZ|BJ)$")
_A_SHARE_PREFIXED = re.compile(r"^(SH|SZ|BJ)(\d{6})$")
_A_SHARE_BARE = re.compile(r"^\d{6}$")
_SHANGHAI_SH = re.compile(r"^(\d{6})\.SH$")
# Exchange -> the suffix the pipeline carries (Yahoo's, so its fallback keeps working).
_A_SHARE_SUFFIX = {"SH": "SS", "SZ": "SZ", "BJ": "BJ"}


def exchange_prefix(code: str) -> str | None:
    """The exchange that lists a 6-digit A-share stock code: SH, SZ or BJ, else None.

    SH: 60 (main board), 68 (STAR / CDR), 90 (B shares)
    SZ: 00 (main board), 30 (ChiNext), 20 (B shares)
    BJ: 92 (codes issued from 2024), 43 / 83 / 87 / 88 and other 4/8 codes
    Fund, bond and index codes (51..., 15..., 11..., 399...) return None.
    """
    c = str(code).strip().zfill(6)[-6:]
    if c.startswith(("60", "68", "90")):
        return "SH"
    if c.startswith(("00", "30", "20")):
        return "SZ"
    if c.startswith(("92", "43", "83", "87", "88")) or c[0] in "48":
        return "BJ"
    return None


def a_share_code(symbol: str) -> str | None:
    """The 6-digit code when ``symbol`` names a China A-share stock, else None.

    A suffix must agree with the code's exchange: ``000001.SS`` is Yahoo's SSE
    Composite index, not the Shenzhen stock ``000001``, and stays a Yahoo symbol.
    """
    if not isinstance(symbol, str):
        return None
    s = symbol.strip().upper()
    if m := _A_SHARE_SUFFIXED.match(s):
        code, exchange = m.group(1), {"SS": "SH"}.get(m.group(2), m.group(2))
        return code if exchange_prefix(code) == exchange else None
    if m := _A_SHARE_PREFIXED.match(s):
        code = m.group(2)
        return code if exchange_prefix(code) == m.group(1) else None
    if _A_SHARE_BARE.match(s):
        return s if exchange_prefix(s) else None
    return None


def a_share_symbol(code: str) -> str:
    """The canonical pipeline symbol for a 6-digit A-share code: ``600519.SS``, ``000001.SZ``, ``920001.BJ``."""
    return f"{code}.{_A_SHARE_SUFFIX[exchange_prefix(code)]}"


# Crypto quote currencies that all map to Yahoo's USD pair. Yahoo lists only
# ``<BASE>-USD`` (not the USDT/USDC stablecoin pairs), so a broker symbol quoted
# in any of these resolves to ``-USD`` (#982). Longest first so ``USDT``/``USDC``
# match before the ``USD`` substring.
_CRYPTO_QUOTES = ("USDT", "USDC", "USD")


def crypto_base(raw: str) -> str | None:
    """Return the crypto base (e.g. ``BTC``) for a known USD/USDT/USDC-quoted
    crypto symbol in any form the pipeline may hold — ``BTC-USD``, ``BTCUSD``,
    ``BTC-USDT`` — or None for non-crypto symbols. Purely syntactic.
    """
    if not isinstance(raw, str):
        return None
    compact = raw.strip().upper().rstrip("+").replace("-", "")
    for quote in _CRYPTO_QUOTES:
        if compact.endswith(quote):
            base = compact[: -len(quote)]
            return base if base in _CRYPTO_BASES else None
    return None


def _normalize_crypto(s: str) -> str | None:
    """Return ``<BASE>-USD`` for a known USD/USDT/USDC-quoted crypto, else None."""
    base = crypto_base(s)
    return f"{base}-USD" if base else None


def normalize_symbol(raw: str) -> str:
    """Map a user/broker symbol to its canonical Yahoo Finance symbol.

    Resolution order (first match wins):
      1. Explicit alias table (metals, energy, index CFDs).
      2. Crypto rule: a known crypto base quoted in USD/USDT/USDC (dashed or
         not) -> ``BASE-USD``.
      3. Forex rule: six letters that are two ISO currency codes -> ``PAIR=X``.
      4. HK rule: a numeric ``.HK`` code -> Yahoo's 4-digit padding
         (``09992.HK`` -> ``9992.HK``, ``700.HK`` -> ``0700.HK``).
      5. China A-share rule: a stock code in any common form -> ``<code>.SS``
         (Shanghai), ``.SZ`` (Shenzhen) or ``.BJ`` (Beijing): ``600519`` and
         ``600519.SH`` -> ``600519.SS``, ``SZ000001`` -> ``000001.SZ``.
      6. Otherwise the upper-cased symbol is returned unchanged (plain
         equities, ETFs, Yahoo-native symbols like ``GC=F`` or ``^GSPC``).

    A trailing ``+`` (broker CFD marker, e.g. ``XAUUSD+``) is stripped before
    matching. The function is purely syntactic — it performs no network
    calls — so it is safe to apply on every request.
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw

    s = raw.strip().upper()
    # Broker CFD/qualifier suffixes Yahoo never uses.
    s = s.rstrip("+")

    crypto = _normalize_crypto(s)
    if s in _ALIASES:
        canonical = _ALIASES[s]
    elif crypto is not None:
        canonical = crypto
    elif len(s) == 6 and s[:3] in _FOREX_CURRENCIES and s[3:] in _FOREX_CURRENCIES:
        canonical = f"{s}=X"
    elif hk := _HK_CODE.match(s):
        canonical = f"{int(hk.group(1)):04d}.HK"
    elif code := a_share_code(s):
        canonical = a_share_symbol(code)
    elif sh := _SHANGHAI_SH.match(s):       # Shanghai indices and funds: 000001.SH -> 000001.SS
        canonical = f"{sh.group(1)}.SS"
    else:
        canonical = s

    if canonical != raw.strip().upper():
        logger.info("Resolved symbol %r to Yahoo symbol %r", raw, canonical)
    return canonical


# Tickers can contain letters, digits, dot, dash, underscore, caret
# (index symbols like ^GSPC), equals (futures like GC=F), and plus
# (forex/CFD symbols like XAUUSD+). None of these enable directory
# traversal, so the value never escapes a containing directory when
# interpolated into a path. Anything else is rejected.
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^=+]+$")


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Validate ``value`` is safe to interpolate into a filesystem path.

    Tickers come from user CLI input or from LLM tool calls, both of which
    can be influenced by attacker-controlled content (e.g. prompt injection
    embedded in fetched news). Without validation, a value like
    ``"../../../etc/foo"`` flows into ``os.path.join`` / ``Path /`` and
    escapes the configured cache, checkpoint, or results directory.

    Returns ``value`` unchanged when it matches the allowed pattern; raises
    ``ValueError`` otherwise.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"ticker must be a non-empty string, got {value!r}")
    if len(value) > max_len:
        raise ValueError(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        raise ValueError(
            f"ticker contains characters not allowed in a filesystem path: {value!r}"
        )
    # The regex above allows '.', so values like '.', '..', '...' would pass,
    # and as a path component they traverse the parent directory. Reject any
    # value that's only dots.
    if set(value) == {"."}:
        raise ValueError(f"ticker cannot consist solely of dots: {value!r}")
    return value
