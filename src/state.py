from typing import TypedDict, List, Annotated
import operator

class ProjectState(TypedDict, total=False):
    run_id: str
    requirement: str
    task_plan: str
    code_file: str
    test_results: str
    iteration: int
    max_iterations: int
    messages: Annotated[List[dict], operator.add]
    is_ready: bool
    regenerate_tests: bool       
    last_failure_key: str         
    app_url: str
    visual_qa_result: str
    visual_diff_pct: float
    visual_analysis: str
    security_result: str
    security_patch: str
    security_report: dict
    performance_result: str
    performance_patch: str
    performance_violations: list
    performance_analysis: str
    performance_stats: dict