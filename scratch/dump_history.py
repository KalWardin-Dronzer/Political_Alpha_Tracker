import json

out = []
with open(r'C:\Users\legen\.gemini\antigravity-ide\brain\4f53a9f7-572a-42aa-8969-3269799b92b4\.system_generated\logs\transcript_full.jsonl', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'PLANNER_RESPONSE' and not data.get('tool_calls') and data.get('content'):
            out.append(data.get('content'))

with open(r'C:\Users\legen\OneDrive\Documents\QEDS\Insider trading\scratch\chat_history.txt', 'w', encoding='utf-8') as f:
    for i, msg in enumerate(out[-5:]):
        f.write(f"--- MSG {i} ---\n{msg}\n")
