# Multi-Agent Dev Team

**A self-healing multi-agent pipeline that plans, codes, tests, verifies visually, and scans for security — autonomously.**

Most AI code generators stop at "it works on my machine." This project runs the code through **six validation layers** and **self-heals** on failure — catching the bugs that demos miss.

## Architecture

```mermaid
graph TD
    Start([User Requirement]) --> PM[PM Agent]
    PM --> Coder[Coder Agent]
    Coder --> QA[QA Agent<br/>6 validation layers]
    QA -->|Pass| Visual[Visual QA Agent]
    QA -->|Fail| Coder
    Visual -->|Pass| Security[Security Agent]
    Visual -->|Fail| Coder
    Security -->|Clean| Done([Production Ready])
    Security -->|Vulnerable| Coder
```

GitHub renders Mermaid diagrams natively. This is worth adding — interviewers love visual architecture.
## Tech Stack

- **Orchestration**: LangGraph (stateful multi-agent graphs)
- **LLM**: Ollama (qwen2.5-coder, llama3.2) — local, zero-cost
- **API**: FastAPI with Server-Sent Events
- **Persistence**: SQLite
- **Testing**: pytest
- **Visual**: Playwright + Pillow
- **Security**: Bandit
- **Dashboard**: Vanilla HTML/CSS/JS

## Quick Start
# Setup
pip install -r requirements.txt
playwright install chromium

# Start Ollama
ollama pull llama3.2:3b
ollama serve

# Run
uvicorn api.server:api --port 8000

## Known Limitations
Stateful classes: 3B models can't reason about state transitions. RateLimiter tests become self-contradictory.

Hash computation: LLMs hallucinate MD5/SHA values. Mitigated by the consistency check.

Language: Python only (Bandit scans Python, pytest runs Python).

Hardware: Runs on 4GB RAM but only with 1.5B-3B models.

##	Findings
1	LLMs hallucinate computed values — needs validation
2	Coding ≠ test generation — needs different strategies
3	Small models can't reason about state — needs bigger model
4	Tests can pass while testing nothing — Caught by stub check
5	Multi-agent loops need invariants — otherwise infinite loop
6	Prompts leak into code — Caught by AST sanitizer
7	Test files redefine imports	— Caught by validator
8	Ambiguous requirements break test gen	— Caught by behavior extraction
9	Hardware constrains model choice — Tradeoff, not a bug
10	Pipeline detects, but can't always fix — Fundamental limit

## Results
<img width="943" height="635" alt="maad5" src="https://github.com/user-attachments/assets/ff68291d-db96-4d78-a7c7-36f64c4c511d" />
<img width="972" height="605" alt="maad7" src="https://github.com/user-attachments/assets/8e15c303-5497-47fc-b5cd-347d65ed6960" />
<img width="990" height="624" alt="maad8" src="https://github.com/user-attachments/assets/182f5178-d5ab-47ac-a021-4ca5aab9c28b" />
<img width="955" height="564" alt="maad10" src="https://github.com/user-attachments/assets/299a4764-3a29-496b-9fd1-03d21ee34413" />
<img width="954" height="602" alt="maad11" src="https://github.com/user-attachments/assets/a5edfeef-f525-4943-9533-47fdd336ffb1" />
<img width="960" height="585" alt="maad12" src="https://github.com/user-attachments/assets/6ed7d4f2-f3c4-4ee8-844e-8508b2266375" />
<img width="951" height="471" alt="maad13" src="https://github.com/user-attachments/assets/458dd3c8-ad80-43f0-9e49-c8af35127fc6" />
<img width="949" height="625" alt="maad14" src="https://github.com/user-attachments/assets/1641cb2d-da17-44b3-a129-82bd5ce9e5ec" />
<img width="846" height="610" alt="maad15" src="https://github.com/user-attachments/assets/ebdf3746-091d-4ef2-9774-7f3459d93be1" />




