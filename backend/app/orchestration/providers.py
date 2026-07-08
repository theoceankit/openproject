from app.providers.base import ModelProvider
from app.providers.factory import get_provider


def node_provider() -> ModelProvider:
    """The only sanctioned way a graph node may reach a model; never import a provider SDK directly."""
    return get_provider()


def node_call_site(state, node_name: str) -> str:
    return f"{state['call_site']}:{node_name}"
