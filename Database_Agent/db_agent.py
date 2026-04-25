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
        )

        message = response.choices[0].message

        # Append assistant turn to history
        messages.append({"role": "assistant", "content": message.content,
                          "tool_calls": message.tool_calls})

        # No tool calls — model is done
        if not message.tool_calls:
            print("\n[done] Agent returned final response")
            return message.content or ""

        # Execute each tool call
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

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
