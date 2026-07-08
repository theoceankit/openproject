from typing import NotRequired

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.orchestration.checkpointer import get_checkpointer
from app.orchestration.providers import node_call_site, node_provider
from app.orchestration.state import BaseGraphState

CALL_SITE = "orchestration.poc"


class PocState(BaseGraphState):
    received: NotRequired[str]
    result: NotRequired[str]


async def _await_input(state: PocState) -> dict:
    received = interrupt({"question": "provide a token"})
    return {"received": received}


async def _finalize(state: PocState) -> dict:
    await node_provider().embed(["poc"], call_site=node_call_site(state, "finalize"))
    return {"result": f"done:{state['received']}"}


def _build_graph():
    builder = StateGraph(PocState)
    builder.add_node("await_input", _await_input)
    builder.add_node("finalize", _finalize)
    builder.add_edge(START, "await_input")
    builder.add_edge("await_input", "finalize")
    builder.add_edge("finalize", END)
    return builder


async def start_poc(thread_id: str, project_id: str | None = None) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    async with get_checkpointer() as checkpointer:
        graph = _build_graph().compile(checkpointer=checkpointer)
        result = await graph.ainvoke({"call_site": CALL_SITE, "project_id": project_id}, config=config)
        return result["__interrupt__"][0].value


async def resume_poc(thread_id: str, value: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    async with get_checkpointer() as checkpointer:
        graph = _build_graph().compile(checkpointer=checkpointer)
        state = await graph.aget_state(config)
        if not state.next:
            return state.values
        return await graph.ainvoke(Command(resume=value), config=config)
