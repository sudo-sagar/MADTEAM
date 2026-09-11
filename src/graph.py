from langgraph.graph import StateGraph, END
from src.state import ProjectState
from src.agents.pm_agent import pm_agent
from src.agents.coder_agent import coder_agent
from src.agents.qa_agent import qa_agent

def should_continue(state: dict) -> str:
    """Decide whether to keep iterating or finish"""
    if state.get("is_ready", False):
        return "finish"
    if state.get("iteration", 0) > 3:  # Max 3 fix cycles
        print("⚠️ Max iterations reached. Manual review needed.")
        return "finish"
    return "continue"

# Build the graph
graph = StateGraph(ProjectState)

# Add nodes
graph.add_node("pm", pm_agent)
graph.add_node("coder", coder_agent)
graph.add_node("qa", qa_agent)

# Add edges
graph.set_entry_point("pm")
graph.add_edge("pm", "coder")
graph.add_edge("coder", "qa")

# Add conditional routing with self-healing
graph.add_conditional_edges(
    "qa",
    should_continue,
    {
        "continue": "coder",  # Send back for fixes
        "finish": END
    }
)

# Compile
app = graph.compile()