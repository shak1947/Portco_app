"""
Batch Meeting Notes Processor
- Scans the /notes folder for all .txt files
- For each file, extracts decisions, action items, open questions
- Writes a summary .md file to /summaries for each one
"""

import os
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-opus-4-5"

NOTES_DIR = "notes"
SUMMARIES_DIR = "summaries"

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
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
        "name": "list_directory",
        "description": "List all files in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
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
        elif name == "list_directory":
            return json.dumps(os.listdir(inputs["path"]))
    except Exception as e:
        return f"ERROR: {e}"

def run_agent(task):
    messages = [{"role": "user", "content": task}]

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
                    return block.text

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"    [tool] {block.name}({json.dumps(block.input)})")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})

# Main
os.makedirs(SUMMARIES_DIR, exist_ok=True)
notes_files = [f for f in os.listdir(NOTES_DIR) if f.endswith(".txt")]

if not notes_files:
    print(f"No .txt files found in /{NOTES_DIR}. Add some and rerun.")
else:
    print(f"Found {len(notes_files)} notes files. Processing...\n")

    for filename in notes_files:
        notes_path = os.path.join(NOTES_DIR, filename)
        summary_path = os.path.join(SUMMARIES_DIR, filename.replace(".txt", ".md"))

        print(f"Processing: {filename}")
        run_agent(
            f"Read the file '{notes_path}'. "
            f"Extract: 1) decisions made, 2) action items with owners and due dates, 3) open questions. "
            f"Write a clean markdown summary to '{summary_path}'."
        )
        print(f"Done -> {summary_path}\n")

    print(f"All done. Check the /{SUMMARIES_DIR} folder.")
