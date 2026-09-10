from dotenv import load_dotenv
from src.graph import app
from src.state import ProjectState

load_dotenv()

def main():
    # Initial state
    initial_state: ProjectState = {
        "requirement": "Build a function that calculates the Fibonacci sequence",
        "task_plan": "",
        "code_file": "",
        "test_results": "",
        "iteration": 0,
        "max_iterations": 5,
        "messages": [],
        "is_ready": False
    }
    
    print("🚀 Starting Multi-Agent Dev Team...")
    print(f"📋 Requirement: {initial_state['requirement']}")
    print("-" * 50)
    
    # Run the workflow
    final_state = app.invoke(initial_state)
    
    print("-" * 50)
    if final_state["is_ready"]:
        print("✅ SUCCESS: Code is production-ready!")
    else:
        print("⚠️ Manual review needed.")

if __name__ == "__main__":
    main()