from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uuid
from src.graph import app as agent_graph

api = FastAPI(title="Multi-Agent Dev Team API")

# In-memory store (swap for Redis/Postgres later)
RUNS = {}

class RunRequest(BaseModel):
    requirement: str
    max_iterations: int = 3

@api.post("/runs")
async def create_run(req: RunRequest, background: BackgroundTasks):
    """Start a new multi-agent run"""
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {"status": "queued", "requirement": req.requirement}
    background.add_task(execute_run, run_id, req)
    return {"run_id": run_id, "status": "queued"}

async def execute_run(run_id: str, req: RunRequest):
    """Execute the agent graph and stream updates"""
    RUNS[run_id]["status"] = "running"
    
    initial_state = {
        "requirement": req.requirement,
        "task_plan": "",
        "code_file": "",
        "test_results": "",
        "iteration": 0,
        "max_iterations": req.max_iterations,
        "messages": [],
        "is_ready": False
    }
    
    # Stream events from LangGraph
    async for event in agent_graph.astream(initial_state):
        RUNS[run_id]["events"] = RUNS[run_id].get("events", []) + [event]
    
    RUNS[run_id]["status"] = "complete"

@api.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get status of a run"""
    return RUNS.get(run_id, {"error": "not found"})

@api.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """SSE stream of live agent progress"""
    async def event_generator():
        # Yield events as they arrive
        while RUNS.get(run_id, {}).get("status") != "complete":
            yield f"data: {RUNS.get(run_id, {}).get('status', 'unknown')}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")