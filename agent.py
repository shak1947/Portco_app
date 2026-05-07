import json
import anthropic







client = anthropic.Anthropic()
MODEL = "claude-opus-4-5"

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
    }
]

def execute_tool(name, inputs):
    try:
        if name == "read_file":
            with open(inputs["path"], "r", encoding="utf-8") as f:
                return f.read()
        elif name == "write_file":
            with open(inputs["path"], "w", encoding="utf-8") as f:
                f.write(inputs["content"])
            return f"Written: {inputs['path']}"
    except Exception as e:
        return f"ERROR: {e}"

def send_message(messages, user_input):
    messages.append({"role": "user", "content": user_input})

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

# Initial task
messages = []
messages = send_message(messages,
    "Read notes.txt. Extract: 1) decisions, 2) action items with owners, 3) open questions. "
    "Write to summary.md as clean markdown."
)

# Follow-up loop
print("Ask follow-up questions about the notes. Type 'quit' to exit.\n")
while True:
    user_input = input("You: ").strip()
    if user_input.lower() == "quit":
        break
    if user_input:
        messages = send_message(messages, user_input)
