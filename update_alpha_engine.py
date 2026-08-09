import re

file_path = r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading\src\alpha_engine.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix self.model -> self.client
content = content.replace("if not self.model:", "if not self.client:")
content = content.replace("self.model.generate_content", "self.client.models.generate_content(model=\"gemini-flash-lite-latest\", contents=")
# Wait, for self.client.models.generate_content(prompt), we need to replace it correctly
# The old calls are self.model.generate_content(prompt)
# It should be self.client.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
content = re.sub(r"self\.model\.generate_content\((prompt.*?)\)", r"self.client.models.generate_content(model='gemini-flash-lite-latest', contents=\1)", content)

new_methods = """
    def analyze_macro_event(self, text: str) -> dict:
        \"\"\"
        Uses Gemini LLM to parse a generic macro-economic or geopolitical news event
        and extract structural details.
        \"\"\"
        if not self.client:
            return {}

        prompt = (
            "You are a hedge fund analyst identifying Macro-Event Alpha.\\n"
            "Read the following global news/macro event and extract the key economic tailwinds and headwinds.\\n"
            "Return a JSON object with the following keys:\\n"
            "- 'event_type': The category of event (e.g., 'Geopolitical Conflict', 'Trade War', 'Pandemic', 'Monetary Policy').\\n"
            "- 'catalyst': A brief 2-5 word description of the specific catalyst.\\n"
            "- 'impacted_sectors_positive': An array of strings representing the specific micro-niche sectors that benefit.\\n"
            "- 'impacted_sectors_negative': An array of strings representing the specific micro-niche sectors that suffer.\\n"
            "- 'magnitude': How large is the economic impact? Choose 'High', 'Medium', or 'Low'.\\n"
            "- 'summary': A 1-sentence summary of the catalyst.\\n"
            "Return ONLY raw JSON without markdown wrappers.\\n"
            f"TEXT:\\n{text[:6000]}"
        )

        try:
            response = self.client.models.generate_content(model='gemini-flash-lite-latest', contents=prompt)
            res_text = response.text.strip()
            if res_text.startswith("```json"):
                res_text = res_text[7:-3].strip()
            elif res_text.startswith("```"):
                res_text = res_text[3:-3].strip()

            data = json.loads(res_text)
            return data
        except Exception as e:
            logger.error(f"Gemini macro event analysis failed: {e}")
            return {}

    def check_company_macro_benefit(self, company_name: str, company_niche: str, event_summary: str) -> bool:
        \"\"\"
        Directly queries the LLM to determine if a specific company benefits from a macro event.
        Returns True if it's a clear beneficiary.
        \"\"\"
        if not self.client:
            return False

        prompt = (
            "You are a hedge fund analyst.\\n"
            f"A major macro event has occurred: {event_summary}\\n"
            f"We are evaluating a company named '{company_name}' operating in the niche: '{company_niche}'.\\n"
            "Does this company directly and clearly benefit economically from this macro event? "
            "Answer ONLY with a boolean 'true' or 'false'. Return raw JSON.\\n"
            "Example output:\\n"
            "true"
        )
        
        try:
            response = self.client.models.generate_content(model='gemini-flash-lite-latest', contents=prompt)
            res_text = response.text.strip().lower()
            return 'true' in res_text
        except Exception as e:
            logger.error(f"Gemini company benefit check failed: {e}")
            return False
"""

# Append the new methods
if "def analyze_macro_event(" not in content:
    content += new_methods

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated alpha_engine.py successfully.")
