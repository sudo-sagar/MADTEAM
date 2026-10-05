#from langchain_openai import ChatOpenAI
#from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.db import append_event

def pm_agent(state: dict) -> dict:
    print("\n [PM] Analyzing requirements...")
    append_event(state["run_id"], {"agent": "pm", "status": "running", "message": "Analyzing requirements"})
    
    llm = ChatOllama(model="llama3.2:3b", temperature=0.3, num_ctx=2048)
    
    messages = [
        SystemMessage(content="""You are a Technical Project Manager. 
        Decompose user requirements into a clear implementation plan.
        List files needed and what each should do."""),
        HumanMessage(content=f"Requirement: {state['requirement']}")
    ]
    
    response = llm.invoke(messages)    # ... your existing LLM call ...
    
    append_event(state["run_id"], {"agent": "pm", "status": "done", "message": "Plan created"})
    return {**state, "task_plan": response.content}

'''def pm_agent(state: dict) -> dict:
    """Project Manager: Breaks requirements into a plan"""
    print("\n[PM] Analyzing requirements...")
    
    #llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    llm = ChatOllama(model="llama3.2:3b", temperature=0)
    
    messages = [
        SystemMessage(content="""You are a Technical Project Manager. 
        Decompose user requirements into a clear implementation plan.
        List files needed and what each should do."""),
        HumanMessage(content=f"Requirement: {state['requirement']}")
    ]
    
    response = llm.invoke(messages)
    
    return {
        **state,
        "task_plan": response.content,
        "iteration": state.get("iteration", 0) + 1
    }
'''