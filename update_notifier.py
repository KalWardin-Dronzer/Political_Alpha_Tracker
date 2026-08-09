file_path = r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading\src\notifier.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

new_method = """
    def send_macro_event_alert(self, company: dict, connection: dict, event: dict):
        \"\"\"Send an alert for a Generalized Macro Event benefiting a connected company.\"\"\"
        scrip = company.get("scrip_code", "")
        company_name = company.get("name", "Unknown")
        score = connection.get("alpha_score", 0)
        
        lines = [
            "🌍 <b>GLOBAL MACRO-EVENT TAILWIND DETECTED</b> 🌍",
            "",
            f"<b>Company:</b> {company_name} (BSE: {scrip})",
            f"<b>Micro-Niche:</b> {company.get('micro_niche', 'Unknown').title()}",
            "",
            "📰 <b>Global Macro Catalyst:</b>",
            f"• <b>Event Type:</b> {event.get('event_type')}",
            f"• <b>Catalyst:</b> {event.get('catalyst')}",
            f"• <b>Magnitude:</b> {event.get('magnitude')}",
            f"• <b>Summary:</b> {event.get('summary')}",
            f"• <a href='{event.get('link')}'>Read Official Source</a>",
            "",
            "🕸️ <b>Political Connection:</b>",
            f"• Top Connection Score: {score:.2f}",
            f"• Director: {connection['director_name']}",
            f"• Donor: {connection['donor_company_name']}",
        ]
        
        if connection.get('is_bureaucrat'):
            lines.append("")
            lines.append("🕴️ <b>DEEP STATE SIGNAL:</b>")
            lines.append(f"<i>{connection['director_name']} is a former high-ranking bureaucrat (IAS/IPS/IRS).</i>")

        lines.extend([
            "",
            "<i>A generalized global macro event is creating massive tailwinds for this company's specific niche.</i>"
        ])
        
        self._send_message("\\n".join(lines))
"""

if "def send_macro_event_alert" not in content:
    content = content.replace("def send_system_alert(", new_method + "\n    def send_system_alert(")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated notifier.py successfully.")
else:
    print("notifier.py already updated.")
