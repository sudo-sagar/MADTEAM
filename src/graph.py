
from langgraph.graph import StateGraph, END
from src.state import ProjectState
from src.agents.pm_agent import pm_agent
from src.agents.coder_agent import coder_agent
from src.agents.qa_agent import qa_agent
from src.agents.visualqa import visual_qa_agent
from src.agents.security_agent import security_agent


def route_after_qa(state: dict) -> str:
    if state.get("is_ready"):
        return "visual_qa"
    if state.get("iteration", 0) > 3:
        return "finish"
    return "coder"


def route_after_visual(state: dict) -> str:
    result = state.get("visual_qa_result", "")
    if result.startswith("regression"):
        if state.get("iteration", 0) > 3:
            return "finish"
        return "coder"
    return "security"


def route_after_security(state: dict) -> str:
    if state.get("security_patch"):
        if state.get("iteration", 0) > 3:
            return "finish"
        return "coder"
    return "finish"


graph = StateGraph(ProjectState)
graph.add_node("pm", pm_agent)
graph.add_node("coder", coder_agent)
graph.add_node("qa", qa_agent)
graph.add_node("visual_qa", visual_qa_agent)
graph.add_node("security", security_agent)

graph.set_entry_point("pm")
graph.add_edge("pm", "coder")
graph.add_edge("coder", "qa")

graph.add_conditional_edges("qa", route_after_qa, {
    "coder": "coder",
    "visual_qa": "visual_qa",
    "finish": END,
})

graph.add_conditional_edges("visual_qa", route_after_visual, {
    "coder": "coder",
    "security": "security",
    "finish": END,
})

graph.add_conditional_edges("security", route_after_security, {
    "coder": "coder",
    "finish": END,
})

app = graph.compile()