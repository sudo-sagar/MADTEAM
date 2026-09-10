#from langchain_openai import ChatOpenAI
#from langchain_community.chat_models import ChatOllama
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from src.tools.file_tools import write_file, read_file

def coder_agent(state: dict) -> dict:
    """Coder Agent: Writes code and self-corrects based on QA feedback"""
    
    print("\n💻 [Coder] Writing code...")
    
    # Determine if this is a fix iteration or initial write
    is_fix = state.get("test_results") and "TESTS FAILED" in state.get("test_results", "")
    
    if is_fix:
        print("🔄 [Coder] Self-correcting based on QA feedback...")
        error_context = state.get("test_results", "")
        code_file = state.get("code_file", "")
        existing_code = read_file.invoke({"filepath": code_file}) if code_file else ""
    else:
        error_context = ""
        existing_code = ""
    
    #llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    llm = ChatOllama(model="llama3.2:3b", temperature=0)
    
    # Build the prompt
    if is_fix:
        messages = [
            SystemMessage(content="""You are a Senior Software Engineer specializing in self-healing code.
            
            **CRITICAL INSTRUCTION**: 
            1. Read the test failure logs carefully
            2. Fix ONLY the issues mentioned in the errors
            3. Do NOT change working code
            4. Return the COMPLETE fixed code (not just the fix)
            5. Ensure all imports and dependencies are included"""),
            
            HumanMessage(content=f"""
            ORIGINAL REQUIREMENT: {state['requirement']}
            
            PLAN: {state['task_plan']}
            
            CURRENT CODE:
            {existing_code}
            
            TEST FAILURES:
            {error_context}
            
            Please fix the code to pass all tests. Return the complete corrected code.
            """)
        ]
    else:
        messages = [
            SystemMessage(content="""You are a Senior Software Engineer.
            Write clean, production-ready Python code that follows best practices.
            Include docstrings, type hints, and error handling.
            Write the complete implementation."""),
            
            HumanMessage(content=f"""
            REQUIREMENT: {state['requirement']}
            
            IMPLEMENTATION PLAN:
            {state['task_plan']}
            
            Write the complete Python implementation in a single file.
            Include all necessary imports and error handling.
            """)
        ]
    
    response = llm.invoke(messages)
    code_content = response.content
    
    # Extract code from markdown if present
    if "```python" in code_content:
        code_content = code_content.split("```python")[1].split("```")[0].strip()
    elif "```" in code_content:
        code_content = code_content.split("```")[1].split("```")[0].strip()
    
    # Write the file
    filepath = "workspace/code/solution.py"
    write_file.invoke({"filepath": filepath, "content": code_content})
    
    # Also generate tests if this is the first iteration
    if not is_fix:
        test_code = generate_tests(llm, state['requirement'], code_content)
        write_file.invoke({"filepath": "workspace/tests/test_code.py", "content": test_code})
    
    return {
        **state,
        "code_file": filepath,
        "messages": state.get("messages", []) + [{
            "role": "coder",
            "content": f"Wrote code to {filepath}" + (" (self-corrected)" if is_fix else "")
        }]
    }

def generate_tests(llm, requirement: str, code: str) -> str:
    """Generate comprehensive test suite"""
    print("🧪 [Coder] Generating tests...")
    
    messages = [
        SystemMessage(content="""You are a QA Engineer.
        Generate comprehensive pytest test cases that cover:
        - Happy path
        - Edge cases
        - Error handling
        - Boundary conditions
        Return ONLY the test code, no explanations.
        Use pytest fixtures if appropriate."""),
        
        HumanMessage(content=f"""
        REQUIREMENT: {requirement}
        
        CODE TO TEST:
        {code}
        
        Generate complete pytest test file.
        """)
    ]
    
    response = llm.invoke(messages)
    test_code = response.content
    
    # Extract from markdown
    if "```python" in test_code:
        test_code = test_code.split("```python")[1].split("```")[0].strip()
    elif "```" in test_code:
        test_code = test_code.split("```")[1].split("```")[0].strip()
    
    return test_code
