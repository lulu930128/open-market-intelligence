from __future__ import annotations


class USMarketDataFetchError(Exception):
    """Raised when a US market provider payload cannot be fetched or validated."""


class USStockNotFoundError(Exception):
    pass


class USMarketConfigurationError(Exception):
    pass


class USWatchlistGroupNotFoundError(Exception):
    pass


class USWatchlistGroupNotEmptyError(Exception):
    pass


class USWatchlistInvalidTreeError(Exception):
    pass


class USWatchlistItemNotFoundError(Exception):
    pass


class USWatchlistDuplicateItemError(Exception):
    pass
