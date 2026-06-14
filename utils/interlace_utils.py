import config
from interlace.client import InterlaceClient


def get_interlace_client() -> InterlaceClient:
    """
    Get an Interlace client instance configured based on the current mode.
    
    Returns:
        InterlaceClient: A configured Interlace client instance
    """
    return InterlaceClient(
        url=config.INTERLACE_DEV.get('base_url') if config.INTERLACE_MODE == 'dev' else config.INTERLACE_PROD.get('base_url'),
        api_key=config.INTERLACE_DEV.get('client_id') if config.INTERLACE_MODE == 'dev' else config.INTERLACE_PROD.get('client_id')
    ) 