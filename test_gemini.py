import os
import litellm
from dotenv import load_dotenv

def test_gemini_connection():
    # 1. Load environment variables
    load_dotenv()
    
    api_key = os.getenv("GOOGLE_API_KEY")
    
    print("--- Environment Check ---")
    if not api_key:
        print("❌ GOOGLE_API_KEY not found in .env file.")
        return
    else:
        # Print masked key for verification
        masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "****"
        print(f"✅ GOOGLE_API_KEY found: {masked_key}")

    # 2. Test models
    test_models = [
        "google/gemini-1.5-pro",        # New standard
        "google/gemini-1.5-flash",      # High availability
        "gemini/gemini-1.5-pro",        # Legacy/AI Studio direct
        "gemini/gemini-2.0-flash-exp",  # Experimental
        "gemini/gemini-1.5-pro-latest"  # Versioned
    ]

    print("\n--- LiteLLM API Call Test ---")
    
    for model in test_models:
        print(f"\nTrying model: {model}...")
        try:
            # We pass the key explicitly like your app.py does
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": "Say 'Gemini is active' in 3 words."}],
                api_key=api_key
            )
            
            answer = response.choices[0].message.content
            print(f"✅ Success!")
            print(f"Response: {answer}")
            
        except Exception as e:
            print(f"❌ Failed for {model}")
            print(f"Error Type: {type(e).__name__}")
            print(f"Error Message: {str(e)}")
            
            if "404" in str(e):
                print("Hint: The model name might be incorrect or your API key doesn't have access to this specific version.")
            if "401" in str(e) or "API_KEY_INVALID" in str(e):
                print("Hint: Your API key appears to be invalid for Google AI Studio.")

if __name__ == "__main__":
    # Enable verbose logging to see exactly what LiteLLM sends
    litellm.set_verbose = True
    test_gemini_connection()