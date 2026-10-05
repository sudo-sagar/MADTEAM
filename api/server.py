import uuid
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

from src.db import init_db, create_run as db_create_run, update_run, get_run as db_get_run, list_runs, append_event
from src.graph import app as agent_graph

api = FastAPI(title="Multi-Agent Dev Team API")


@api.on_event("startup")
async def startup():
    init_db()


class RunRequest(BaseModel):
    requirement: str
    max_iterations: int = 3


@api.post("/api/runs")
async def start_run(req: RunRequest, background: BackgroundTasks):
    print(f"RECEIVED REQUIREMENT: {req.requirement!r}")   # ← ADD THIS LINE
    run_id = str(uuid.uuid4())
    db_create_run(run_id, req.requirement)
    background.add_task(execute_run, run_id, req)
    return {"run_id": run_id, "status": "queued"}


async def execute_run(run_id: str, req: RunRequest):
    update_run(run_id, status="running")

    initial_state = {
        "run_id": run_id,
        "requirement": req.requirement,
        "task_plan": "",
        "code_file": "",
        "test_results": "",
        "iteration": 0,
        "max_iterations": req.max_iterations,
        "messages": [],
        "is_ready": False,
        "app_url": "http://localhost:8000",
        "visual_qa_result": "",
        "visual_diff_pct": 0.0,
        "visual_analysis": "",
        "security_result": "",
        "security_patch": "",
        "regenerate_tests": False,
        "last_failure_key": "",
    }

    try:
        final_state = await asyncio.to_thread(agent_graph.invoke, initial_state)
        update_run(
            run_id,
            status="complete",
            iteration=final_state.get("iteration", 0),
            is_ready=int(final_state.get("is_ready", False)),
            code_file=final_state.get("code_file", ""),
            test_results=final_state.get("test_results", ""),
        )
        append_event(run_id, {
            "agent": "system",
            "status": "done",
            "message": "Run complete",
        })
    except Exception as e:
        update_run(run_id, status="error", error=str(e))
        append_event(run_id, {
            "agent": "system",
            "status": "error",
            "message": str(e),
        })


@api.get("/api/runs")
async def get_runs():
    return list_runs()


@api.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@api.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    async def event_generator():
        last_count = 0
        while True:
            run = db_get_run(run_id)
            if not run:
                yield "event: error\ndata: not found\n\n"
                break

            events = run.get("events", [])
            while last_count < len(events):
                evt = events[last_count]
                yield f"event: agent\ndata: {evt}\n\n"
                last_count += 1

            if run["status"] in ("complete", "error"):
                yield f"event: done\ndata: {run['status']}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@api.get("/artifact/{run_id}")
async def get_artifact(run_id: str):
    """Return the rendered visual artifact screenshot for a run."""
    path = Path("workspace/screenshots") / (run_id + ".png")
    if not path.exists():
        raise HTTPException(404, "artifact not found")
    return FileResponse(str(path), media_type="image/png")


@api.get("/code/{run_id}")
async def get_code(run_id: str):
    """Return the generated code for a run."""
    run = db_get_run(run_id)
    if not run or not run.get("code_file"):
        raise HTTPException(404, "code not found")
    code_path = Path(run["code_file"])
    if not code_path.exists():
        raise HTTPException(404, "code file missing")
    return FileResponse(str(code_path), media_type="text/plain")
# ─── Serve the dashboard LAST ───
static_dir = Path(__file__).parent.parent / "static"
api.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")