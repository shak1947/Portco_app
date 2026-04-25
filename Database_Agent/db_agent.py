"""
agent.py — Model-agnostic AI agent using LiteLLM.

Swap MODEL in .env to change from Claude to Gemini to GPT with zero code changes.
LiteLLM handles all translation between provider APIs.
"""

import os
import json
import litellm
from dotenv import load_dotenv
from database import seed_sample_data
from tools import TOOL_DEFINITIONS, execute_tool
from prompts import SYSTEM_PROMPT

load_dotenv()

# ── Config from .env — no hardcoded values ─────────────────────────────────────
MODEL         = os.getenv("MODEL", "anthropic/claude-sonnet-4-6")
MAX_TOKENS    = int(os.getenv("MAX_TOKENS", "4096"))
MAX_ITER      = int(os.getenv("MAX_ITERATIONS", "10"))

# LiteLLM picks up API keys from environment automatically:
# ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY, etc.
litellm.set_verbose = False


def _serialize_tool_call(tool_call):
    """Convert ChatCompletionMessageToolCall to a plain dict."""
    try:
        function = getattr(tool_call, "function", None)
        func_dict = {}
        if function:
            func_dict["name"] = str(getattr(function, "name", ""))
            func_dict["arguments"] = str(getattr(function, "arguments", ""))
        
        return {
            "id": str(getattr(tool_call, "id", "")),
            "type": str(getattr(tool_call, "type", "function")),
            "function": func_dict,
        }
    except Exception as e:
        print(f"Failed to serialize tool_call: {e}")
        return {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}


def _parse_tool_args(tool_call):
    function = getattr(tool_call, "function", None)
    if function is None:
        return {}
    raw_args = getattr(function, "arguments", "")
    if isinstance(raw_args, dict):
        return raw_args
    if not isinstance(raw_args, str):
        return {}
    try:
        return json.loads(raw_args)
    except json.JSONDecodeError:
        return {}


def _get_provider_api_key():
    provider = MODEL.split("/")[0].lower() if MODEL else ""
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "gpt": "OPENAI_API_KEY",
    }
    key_name = env_map.get(provider)
    if key_name:
        print(f"Provider {provider} mapped to env var {key_name}")
        return os.getenv(key_name)
    print(f"Provider {provider} has no mapped env var")
    return None


# ── Agentic loop ───────────────────────────────────────────────────────────────
def run_agent(user_question: str) -> str:
    """
    Core agentic loop.

    1. Send user question + tools to LiteLLM (which calls whatever model is in .env)
    2. If model calls a tool -> execute it, append result, loop
    3. If model stops -> return final text response

    This loop is identical regardless of which model is active.
    LiteLLM normalizes the response format so the loop never needs to change.
    """
    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": user_question},
    ]

    print(f"\n{'='*60}")
    print(f"Model:    {MODEL}")
    print(f"Question: {user_question}")
    print(f"{'='*60}")

    for iteration in range(MAX_ITER):
        print(f"\n[iter {iteration+1}]")

        response = litellm.completion(
            model=MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            max_tokens=MAX_TOKENS,
            api_key=_get_provider_api_key(),
        )

        message = response.choices[0].message
        
        # Safely convert tool_calls iterator to list
        try:
            tool_calls_list = list(message.tool_calls) if message.tool_calls else []
        except (TypeError, AttributeError):
            tool_calls_list = []

        # Append assistant turn to history
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [_serialize_tool_call(tc) for tc in tool_calls_list],
        })

        # No tool calls — model is done
        if not tool_calls_list:
            print("\n[done] Agent returned final response")
            return message.content or ""

        # Execute each tool call
        for tool_call in tool_calls_list:
            name = tool_call.function.name
            args = _parse_tool_args(tool_call)

            print(f"  [tool] {name}")
            result = execute_tool(name, args)

            # Append tool result — LiteLLM standard format
            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "name":         name,
                "content":      result,
            })

    return "Max iterations reached without a final response."


# ── Interactive REPL ───────────────────────────────────────────────────────────
def main():
    print("\nPortfolio Database Analysis Agent")
    print(f"Model: {MODEL}")
    print("Type 'quit' to exit.\n")

    # Seed sample data if needed
    seed_sample_data()

    # Starter questions to demonstrate capabilities
    starter_questions = [
        "Which portfolio company has the highest EBITDA margin in 2024-Q4?",
        "Show me the revenue trend for all companies from 2023-Q1 to 2024-Q4.",
        "Which sector has the strongest average YoY growth in the latest quarter?",
        "Compare the top 3 companies by EBITDA in 2024-Q4 vs 2023-Q4.",
    ]

    print("Example questions you can ask:")
    for i, q in enumerate(starter_questions, 1):
        print(f"  {i}. {q}")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        # Allow shortcut: type "1", "2", "3", "4" to run starter questions
        if user_input in ("1","2","3","4"):
            user_input = starter_questions[int(user_input)-1]
            print(f"Running: {user_input}")

        response = run_agent(user_input)
        print(f"\nAgent:\n{response}\n")


if __name__ == "__main__":
    main()
