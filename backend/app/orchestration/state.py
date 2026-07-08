from typing import NotRequired, TypedDict


class BaseGraphState(TypedDict):
    """Every stage graph's state TypedDict should extend this."""

    project_id: NotRequired[str | None]
    call_site: str
