from dotenv import load_dotenv
from src.graph import app
from src.state import ProjectState
import os
import uuid

load_dotenv()

def main():
    # Create workspace directories
    os.makedirs("workspace/code", exist_ok=True)
    os.makedirs("workspace/tests", exist_ok=True)
    
    # Test with a requirement that might initially fail
    initial_state: ProjectState = {
        "run_id": str(uuid.uuid4()),
        "requirement": "Write a Python function `validate_email(email) -> bool` that returns True for valid email addresses and **False for ALL invalid inputs**.This includes empty strings, None, non-string types, and malformed addresses. The function must NEVER raise an exception — every invalid input returns False. Do not add an `if __name__ == '__main__'` block.",
        "task_plan": "",
        "code_file": "",
        "test_results": "",
        "iteration": 0,
        "max_iterations": 3,
        "messages": [],
        "is_ready": False  
        }
    
    print("🚀 Starting Self-Healing Multi-Agent Dev Team...")
    print(f"📋 Requirement: {initial_state['requirement']}")
    print("=" * 60)
    
    # Run the workflow
    final_state = app.invoke(initial_state)
    
    print("=" * 60)
    print("\n📊 FINAL STATUS:")
    print(f"   Iterations: {final_state['iteration']}")
    print(f"   Production Ready: {'✅ YES' if final_state['is_ready'] else 'NO'}")
    
    if final_state['is_ready']:
        print("\n🎉 SUCCESS: Code passed all tests and is production-ready!")
    else:
        print("\n⚠️ Manual review needed. Check workspace/code/solution.py")
    
    # Show the code
    if os.path.exists("workspace/code/solution.py"):
        print("\n📄 Generated Code:")
        print("-" * 60)
        with open("workspace/code/solution.py", 'r') as f:
            print(f.read())
        print("-" * 60)

if __name__ == "__main__":
    main()