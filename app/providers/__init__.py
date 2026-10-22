from ..config import Settings
from .amadeus import AmadeusProvider, FallbackProvider
from .base import CachedProvider, DataProvider
from .synthetic import SyntheticProvider


def get_provider(settings: Settings) -> DataProvider:
    """Build a fresh cached provider for one request (cache lives only for that request)."""
    if settings.data_provider == "amadeus" and settings.amadeus_client_id and settings.amadeus_client_secret:
        return CachedProvider(FallbackProvider(AmadeusProvider(settings), SyntheticProvider()))
    return CachedProvider(SyntheticProvider())
