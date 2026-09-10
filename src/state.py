from typing import TypedDict, List, Annotated
import operator

class ProjectState(TypedDict):
    """The state that flows through your multi-agent system"""
    requirement: str                    # User's request
    task_plan: str                      # PM's decomposition
    code_file: str                      # Where code is saved
    test_results: str                   # QA's test output
    iteration: int                      # How many fix cycles
    max_iterations: int                 # Max fix attempts (prevents infinite loops)
    messages: Annotated[List[dict], operator.add]  # Conversation history
    is_ready: bool                      # Production-ready flag