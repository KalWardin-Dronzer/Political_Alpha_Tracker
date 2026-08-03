import streamlit as st
import sqlite3
import pandas as pd
import pathlib
import os
import json
import streamlit.components.v1 as components
import google.generativeai as genai
from src.config import CACHE_DB
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

st.set_page_config(
    page_title="Political Alpha Tracker",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load custom CSS
with open("assets/style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ----------------------------------------------------------------------
# Database Helper
# ----------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_data(query: str, params=()) -> pd.DataFrame:
    conn = sqlite3.connect(str(CACHE_DB))
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

@st.cache_data(ttl=60)
def get_kpis():
    conn = sqlite3.connect(str(CACHE_DB))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM virtual_portfolio")
    active_positions = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(net_pnl) FROM trade_history")
    total_pnl = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT COUNT(*) FROM announcements WHERE is_contract=1")
    tenders_found = cursor.fetchone()[0]
    
    conn.close()
    return active_positions, total_pnl, tenders_found

# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
st.sidebar.title("📈 Alpha Tracker")
st.sidebar.markdown("Quantamental Trading Engine dashboard.")

tab = st.sidebar.radio("Navigation", ["Overview", "Conviction Rankings", "Knowledge Graph", "Paper Portfolio", "Chat with Data"])

# ----------------------------------------------------------------------
# Overview Tab
# ----------------------------------------------------------------------
if tab == "Overview":
    st.header("System Overview")
    st.markdown("Live metrics from the Alpha Tracker engine.")
    
    active_positions, total_pnl, tenders_found = get_kpis()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Active Positions", active_positions)
    col2.metric("Realized PnL (Rs.)", f"₹ {total_pnl:,.2f}")
    col3.metric("Material Tenders Parsed", tenders_found)
    
    st.subheader("Recent Corporate Announcements")
    recent_announcements = load_data(
        "SELECT scrip_code, title, date, contract_value_cr FROM announcements WHERE is_contract=1 ORDER BY date DESC LIMIT 10"
    )
    st.dataframe(recent_announcements, use_container_width=True)

# ----------------------------------------------------------------------
# Conviction Rankings Tab
# ----------------------------------------------------------------------
elif tab == "Conviction Rankings":
    st.header("Top Alpha Candidates")
    st.markdown("Companies ranked by hybrid conviction score (Graph centrality + Tender Materiality + Regional Matching).")
    
    df_alphas = load_data("""
        SELECT c.scrip_code, c.name, c.sector, c.market_cap, a.score as alpha_score
        FROM alpha_graph a
        JOIN companies c ON a.cin = c.cin
        ORDER BY a.score DESC
        LIMIT 50
    """)
    if not df_alphas.empty:
        st.dataframe(
            df_alphas.style.background_gradient(subset=['alpha_score'], cmap='Oranges'),
            use_container_width=True
        )
    else:
        st.info("No alpha scores generated yet. Run the alpha_engine.")

# ----------------------------------------------------------------------
# Knowledge Graph Tab
# ----------------------------------------------------------------------
elif tab == "Knowledge Graph":
    st.header("Political-Corporate Graph")
    st.markdown("Interactive network of companies, directors, electoral trusts, and political parties.")
    
    graph_path = "graph_visualization.html"
    if os.path.exists(graph_path):
        with open(graph_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
        components.html(source_code, height=800, scrolling=True)
    else:
        st.warning(f"{graph_path} not found. Run `visualize.py` first.")

# ----------------------------------------------------------------------
# Paper Portfolio Tab
# ----------------------------------------------------------------------
elif tab == "Paper Portfolio":
    st.header("Virtual Portfolio Performance")
    
    st.subheader("Current Holdings")
    holdings = load_data("SELECT scrip_code, buy_date, buy_price, quantity, invested_amount, conviction_score FROM virtual_portfolio")
    st.dataframe(holdings, use_container_width=True)
    
    st.subheader("Trade History")
    history = load_data("SELECT scrip_code, buy_date, sell_date, buy_price, sell_price, quantity, net_pnl FROM trade_history ORDER BY sell_date DESC")
    st.dataframe(history.style.map(lambda val: 'color: green' if val > 0 else 'color: red', subset=['net_pnl']), use_container_width=True)

# ----------------------------------------------------------------------
# Chat with Data Tab
# ----------------------------------------------------------------------
elif tab == "Chat with Data":
    st.header("Gemini Data Assistant")
    st.markdown("Ask questions in natural language about the database.")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
    if prompt := st.chat_input("E.g., What are the top 3 companies by market cap?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            # Very naive implementation: we just ask gemini to generate SQL or answer directly
            # For a true data app, we would use an agent. Here we just show the integration.
            schema = '''
            companies(scrip_code, name, isin, cin, sector, industry, micro_niche, market_cap, face_value)
            directors(din, cin, name, designation, is_bureaucrat)
            donors(donor_name, donor_cin, amount, trust_name, recipient_party, year)
            announcements(scrip_code, title, date, is_contract, contract_value_cr)
            alpha_graph(din, cin, score)
            virtual_portfolio(scrip_code, buy_date, buy_price, quantity, invested_amount, conviction_score)
            '''
            system_prompt = f"You are a helpful Data Analyst. You have access to a SQLite DB with this schema: {schema}. Answer the user's question. If you need to write a SQL query, provide the exact query in a markdown sql block."
            
            try:
                model = genai.GenerativeModel('gemini-flash-latest', system_instruction=system_prompt)
                response = model.generate_content(prompt)
                
                # If there's a SQL query, try to run it
                reply = response.text
                if "```sql" in reply:
                    sql_query = reply.split("```sql")[1].split("```")[0].strip()
                    try:
                        df_res = load_data(sql_query)
                        st.dataframe(df_res)
                        reply = reply.replace(f"```sql\n{sql_query}\n```", "(Executed SQL Query)")
                    except Exception as e:
                        reply += f"\n\n*Error executing query:* {e}"
                        
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
            except Exception as e:
                st.error(f"Gemini API Error: {e}")
