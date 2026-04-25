# Anthropic Claude API - Basics Tutorial
# ========================================

import anthropic

# ------------------------------
# SETUP
# ------------------------------
# Option 1: Set your API key as an environment variable (recommended):
#   set ANTHROPIC_API_KEY=your-key-here  (Windows CMD)
#   $env:ANTHROPIC_API_KEY="your-key-here"  (PowerShell)
#
# Option 2: Pass it directly (not recommended for production):
#   client = anthropic.Anthropic(api_key="your-key-here")

client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env variable

# ------------------------------
# BASIC API CALL
# ------------------------------
def basic_call():
    """Simple single message to Claude"""
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",  # or "claude-3-haiku-20240307" (cheaper/faster)
        max_tokens=1024,
        messages=[
            {"role": "user", "content": "Hello! What can you help me with?"}
        ]
    )
    
    # The response structure
    print("=== BASIC CALL ===")
    print(f"Response: {message.content[0].text}")
    print(f"Model: {message.model}")
    print(f"Tokens used - Input: {message.usage.input_tokens}, Output: {message.usage.output_tokens}")
    print()

# ------------------------------
# WITH SYSTEM PROMPT
# ------------------------------
def with_system_prompt():
    """Using a system prompt to set Claude's behavior"""
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system="You are a helpful coding assistant. Keep responses brief and include code examples.",
        messages=[
            {"role": "user", "content": "How do I read a file in Python?"}
        ]
    )
    
    print("=== WITH SYSTEM PROMPT ===")
    print(message.content[0].text)
    print()

# ------------------------------
# CONVERSATION (Multi-turn)
# ------------------------------
def conversation():
    """Back-and-forth conversation with context"""
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": "My name is Alex."},
            {"role": "assistant", "content": "Nice to meet you, Alex! How can I help you today?"},
            {"role": "user", "content": "What's my name?"}
        ]
    )
    
    print("=== CONVERSATION ===")
    print(message.content[0].text)
    print()

# ------------------------------
# ADJUSTING PARAMETERS
# ------------------------------
def with_parameters():
    """Controlling creativity with temperature"""
    
    # temperature: 0 = deterministic, 1 = more creative/random
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        temperature=0,  # Very consistent responses
        messages=[
            {"role": "user", "content": "Give me one word that describes the ocean."}
        ]
    )
    
    print("=== WITH PARAMETERS (temp=0) ===")
    print(message.content[0].text)
    print()

# ------------------------------
# RUN EXAMPLES
# ------------------------------
if __name__ == "__main__":
    print("Anthropic Claude API Basics\n")
    
    # Uncomment the examples you want to run:
    basic_call()
    # with_system_prompt()
    # conversation()
    # with_parameters()
