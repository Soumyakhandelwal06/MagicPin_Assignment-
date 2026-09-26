import json
from pathlib import Path
from fastapi.testclient import TestClient
import bot  # Import your bot app
import time
import os

# Inject the user's provided API key so the full LLM chatbot works
# Set GROQ_API_KEY if you want to use Groq (Llama)
# Set GROQ_API_KEY if you want to use Groq (Llama)
os.environ["GROQ_API_KEY"] = "YOUR_GROQ_API_KEY_HERE"



# Create a test client to talk to the bot without needing to start a real server
client = TestClient(bot.app)

def print_chat(sender, message, color):
    # Helper to print colored chat messages
    colors = {"bot": "\033[96m", "user": "\033[92m", "system": "\033[93m", "reset": "\033[0m"}
    c = colors.get(color, colors["reset"])
    print(f"\n{c}[{sender}]{colors['reset']} {message}")

def run_demo():
    print_chat("System", "Starting Chatbot Demo...", "system")
    
    # 1. Load context from the dataset
    ds_dir = Path("expanded_dataset")
    
    print_chat("System", "Loading knowledge about 'Dentists' and 'Dr. Meera's Clinic'...", "system")
    with open(ds_dir / "categories/dentists.json") as f:
        client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "delivered_at": "2026-04-26T10:30:00Z", "payload": json.load(f)})
        
    with open(ds_dir / "merchants/m_001_drmeera_dentist_delhi.json") as f:
        client.post("/v1/context", json={"scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1, "delivered_at": "2026-04-26T10:30:00Z", "payload": json.load(f)})
        
    with open(ds_dir / "triggers/trg_001_research_digest_dentists.json") as f:
        client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_001_research_digest_dentists", "version": 1, "delivered_at": "2026-04-26T10:30:00Z", "payload": json.load(f)})

    time.sleep(1)
    print_chat("System", "Time advances... Triggering the bot to evaluate its tasks.", "system")
    
    # 2. Trigger the bot to send the first message
    tick_payload = {
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    }
    response = client.post("/v1/tick", json=tick_payload).json()
    
    if not response.get("actions"):
        print_chat("System", "Bot decided not to send anything.", "system")
        return
        
    action = response["actions"][0]
    conv_id = action["conversation_id"]
    merchant_id = action["merchant_id"]
    
    # Print the bot's first outbound message
    print_chat("Vera (Bot)", action["body"], "bot")
    print_chat("System", f"(Internal Rationale: {action['rationale']} | CTA type: {action['cta']})", "system")
    
    turn = 2
    # 3. Enter an interactive chat loop
    while True:
        user_input = input("\n\033[92m[You (Dr. Meera)]\033[0m: ")
        if user_input.lower() in ['quit', 'exit']:
            break
            
        reply_payload = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "from_role": "merchant",
            "message": user_input,
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": turn
        }
        
        reply_res = client.post("/v1/reply", json=reply_payload).json()
        bot_action = reply_res.get("action")
        
        if bot_action == "send":
            print_chat("Vera (Bot)", reply_res["body"], "bot")
            print_chat("System", f"(Internal Rationale: {reply_res['rationale']} | CTA type: {reply_res.get('cta')})", "system")
        elif bot_action == "wait":
            print_chat("System", f"Bot went to SLEEP. (Rationale: {reply_res['rationale']})", "system")
            break
        elif bot_action == "end":
            print_chat("System", f"Bot ENDED the conversation. (Rationale: {reply_res['rationale']})", "system")
            break
            
        turn += 1

if __name__ == "__main__":
    run_demo()
