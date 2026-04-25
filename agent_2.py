"""
Step 4: Meeting Notes Agent with Search
Loads API key from .env file automatically.
"""

import os
import json
from dotenv import load_dotenv
import anthropic

load_dotenv()  # reads .env file and sets environment variables
client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY automatically
MODEL = "claude-opus-4-7"

NOTES_DIR = "notes"
SUMMARIES_DIR = "summaries"

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a text file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "search_summaries",
        "description": "Search all summary files for a keyword. Returns matching filenames and the lines that matched.",
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"]
        }
    }
]

def execute_tool(name, inputs):
    try:
        if name == "read_file":
            with open(inputs["path"], "r", encoding="utf-8") as f:
                return f.read()
        elif name == "write_file":
            os.makedirs(os.path.dirname(os.path.abspath(inputs["path"])), exist_ok=True)
            with open(inputs["path"], "w", encoding="utf-8") as f:
                f.write(inputs["content"])
            return f"Written: {inputs['path']}"
        elif name == "search_summaries":
            keyword = inputs["keyword"].lower()
            results = {}
            for fname in os.listdir(SUMMARIES_DIR):
                if not fname.endswith(".md"):
                    continue
                path = os.path.join(SUMMARIES_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                matches = [l.strip() for l in lines if keyword in l.lower()]
                if matches:
                    results[fname] = matches
            if not results:
                return f"No matches found for '{inputs['keyword']}'"
            return json.dumps(results, indent=2)
    except Exception as e:
        return f"ERROR: {e}"

def run_agent(task, messages=None):
    if messages is None:
        messages = []
    messages.append({"role": "user", "content": task})

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            tools=TOOLS,
            messages=messages
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"\nAgent: {block.text}\n")
            return messages

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [tool] {block.name}({json.dumps(block.input)})")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})

# Batch process all notes
os.makedirs(SUMMARIES_DIR, exist_ok=True)
notes_files = [f for f in os.listdir(NOTES_DIR) if f.endswith(".txt")]

print(f"Found {len(notes_files)} notes files. Processing...\n")
for filename in notes_files:
    notes_path = os.path.join(NOTES_DIR, filename)
    summary_path = os.path.join(SUMMARIES_DIR, filename.replace(".txt", ".md"))
    print(f"Processing: {filename}")
    run_agent(
        f"Read '{notes_path}'. Extract: 1) decisions, 2) action items with owners and due dates, "
        f"3) open questions. Write clean markdown to '{summary_path}'."
    )
    print(f"Done -> {summary_path}\n")

# Search loop
print("Summaries ready. Ask questions across all your notes. Type 'quit' to exit.\n")
messages = []
while True:
    user_input = input("You: ").strip()
    if user_input.lower() == "quit":
        break
    if user_input:
        messages = run_agent(user_input, messages)
