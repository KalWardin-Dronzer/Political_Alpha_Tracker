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

tab = st.sidebar.radio("Navigation", ["Overview", "Conviction Rankings", "Knowledge Graph", "Paper Portfolio", "Technical Analysis", "Chat with Data"])

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
    
    st.divider()
    st.subheader("Historical Backtest & ML Performance")
    col_a, col_b = st.columns(2)
    col_a.metric("ML Optimized Win Rate", "69.7%", "+6.8% vs Baseline")
    col_b.metric("1-Year Avg Return (Connected)", "28.24%", "+21.06% vs Benchmark")
    
    st.markdown("##### Post-Event Return Spread (Connected vs Unconnected vs Benchmark)")
    performance_data = pd.DataFrame({
        "Time Window": ["30 Days", "60 Days", "90 Days", "180 Days", "360 Days"],
        "Connected (%)": [4.65, 6.20, 15.68, 27.49, 28.24],
        "Unconnected (%)": [-2.59, -2.18, -1.66, -4.53, 6.07],
        "Benchmark (%)": [0.45, 2.17, 1.94, 4.12, 7.18]
    }).set_index("Time Window")
    st.bar_chart(performance_data)
    
    st.divider()
    st.subheader("Live Alpha Alerts (High Conviction)")
    live_alerts = load_data("SELECT scrip_code, name, alpha_score, alert_date, expires_at FROM held_positions ORDER BY alert_date DESC")
    if not live_alerts.empty:
        st.dataframe(live_alerts)
    else:
        st.info("No active live alerts currently matching conviction criteria.")

    st.subheader("Recent Corporate Announcements (Raw)")
    recent_announcements = load_data(
        "SELECT scrip_code, title, date, contract_value_cr FROM announcements WHERE is_contract=1 ORDER BY date DESC LIMIT 10"
    )
    st.dataframe(recent_announcements)

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
            df_alphas.style.background_gradient(subset=['alpha_score'], cmap='Oranges')
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
    
    col1, col2, col3, col4 = st.columns(4)
    
    with sqlite3.connect(str(CACHE_DB)) as conn:
        invested = conn.execute("SELECT sum(invested_amount) FROM virtual_portfolio").fetchone()[0] or 0.0
        realized_pnl = conn.execute("SELECT sum(net_pnl) FROM trade_history").fetchone()[0] or 0.0
        wins = conn.execute("SELECT COUNT(*) FROM trade_history WHERE net_pnl > 0").fetchone()[0] or 0
        total_trades = conn.execute("SELECT COUNT(*) FROM trade_history").fetchone()[0] or 0
        
    initial_capital = 100000.0
    available_capital = initial_capital + realized_pnl - invested
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    col1.metric("Available Cash (Rs.)", f"₹ {available_capital:,.2f}")
    col2.metric("Invested Capital (Rs.)", f"₹ {invested:,.2f}")
    col3.metric("Realized PnL (Rs.)", f"₹ {realized_pnl:,.2f}", delta=f"{realized_pnl:,.2f}")
    col4.metric("Win Rate", f"{win_rate:.1f}%", f"{wins}/{total_trades} Trades")
    
    st.divider()
    st.subheader("Current Holdings")
    holdings = load_data("SELECT scrip_code, buy_date, buy_price, quantity, invested_amount, conviction_score FROM virtual_portfolio")
    st.dataframe(holdings)
    
    st.subheader("Trade History")
    history = load_data("SELECT scrip_code, buy_date, sell_date, buy_price, sell_price, quantity, net_pnl FROM trade_history ORDER BY sell_date DESC")
    st.dataframe(history.style.map(lambda val: 'color: green' if val > 0 else 'color: red', subset=['net_pnl']))

# ----------------------------------------------------------------------
# Technical Analysis Tab
# ----------------------------------------------------------------------
elif tab == "Technical Analysis":
    st.header("📊 Technical Analysis")
    st.markdown("Interactive charting with RSI, MACD, OBV, SMA crossovers, and ATR trailing stops.")
    
    # Get watchlist companies for the dropdown
    ta_companies = load_data("SELECT scrip_code, name, nse_symbol FROM companies WHERE in_watchlist=1 ORDER BY name")
    
    if ta_companies.empty:
        st.info("No companies in the watchlist yet. Run the pipeline first.")
    else:
        options = [f"{row['name']} ({row['scrip_code']})" for _, row in ta_companies.iterrows()]
        selected = st.selectbox("Select a Company", options)
        
        if selected:
            # Parse selection
            selected_idx = options.index(selected)
            sel_row = ta_companies.iloc[selected_idx]
            sel_scrip = sel_row['scrip_code']
            sel_name = sel_row['name']
            sel_nse = sel_row.get('nse_symbol', '')
            
            if st.button("🔍 Run Technical Analysis", type="primary"):
                with st.spinner(f"Fetching price data and computing indicators for {sel_name}..."):
                    from src.technical_analyzer import TechnicalAnalyzer
                    ta = TechnicalAnalyzer()
                    result = ta.analyze(sel_scrip, sel_name, nse_symbol=sel_nse if sel_nse else None)
                
                if result.price_data is None:
                    st.error(f"Could not fetch price data for {sel_name}. Try again later.")
                else:
                    # Signal banner
                    signal_colors = {"STRONG_BUY": "green", "BUY": "blue", "NEUTRAL": "orange", "AVOID": "red"}
                    signal_emojis = {"STRONG_BUY": "🟢", "BUY": "🔵", "NEUTRAL": "🟡", "AVOID": "🔴"}
                    sig_color = signal_colors.get(result.signal, "gray")
                    sig_emoji = signal_emojis.get(result.signal, "⚪")
                    
                    st.markdown(f"""
                    <div style='background: linear-gradient(135deg, {sig_color}22, {sig_color}11); 
                                border-left: 4px solid {sig_color}; padding: 16px; border-radius: 8px; margin-bottom: 16px;'>
                        <h2 style='margin:0; color: {sig_color};'>{sig_emoji} {result.signal}</h2>
                        <p style='margin: 4px 0 0 0; font-size: 18px;'>Technical Score: <b>{result.score}/10</b> | 
                        Conviction Adjustment: <b>{result.conviction_adjustment:+.1f}</b></p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # KPI row
                    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
                    kpi1.metric("CMP", f"₹{result.current_price:,.2f}" if result.current_price else "N/A")
                    kpi2.metric("RSI (14)", f"{result.rsi:.1f}" if result.rsi else "N/A")
                    kpi3.metric("SMA 50", f"₹{result.sma_50:,.2f}" if result.sma_50 else "N/A")
                    kpi4.metric("SMA 200", f"₹{result.sma_200:,.2f}" if result.sma_200 else "N/A")
                    kpi5.metric("ATR Stop", f"₹{result.atr_stop_loss:,.2f}" if result.atr_stop_loss else "N/A")
                    
                    # Scoring breakdown
                    with st.expander("📋 Scoring Breakdown", expanded=True):
                        for b in result.breakdown:
                            st.text(b)
                    
                    # --- Plotly Charts ---
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                    
                    df = result.price_data.copy()
                    df.index = pd.to_datetime(df.index)
                    # Use last 6 months for readability
                    df = df.tail(130)
                    
                    fig = make_subplots(
                        rows=4, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03,
                        row_heights=[0.45, 0.18, 0.18, 0.19],
                        subplot_titles=(
                            f"{sel_name} — Price + SMA + ATR Stop",
                            "RSI (14)", "MACD (12,26,9)", "On-Balance Volume (OBV)"
                        )
                    )
                    
                    # Row 1: Candlestick + SMA + ATR Stop
                    fig.add_trace(go.Candlestick(
                        x=df.index, open=df['Open'], high=df['High'],
                        low=df['Low'], close=df['Close'], name='Price',
                        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
                    ), row=1, col=1)
                    
                    if 'SMA_50' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['SMA_50'], name='SMA 50',
                            line=dict(color='#ffa726', width=1.5)
                        ), row=1, col=1)
                    if 'SMA_200' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['SMA_200'], name='SMA 200',
                            line=dict(color='#42a5f5', width=1.5)
                        ), row=1, col=1)
                    if 'VWAP' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['VWAP'], name='VWAP',
                            line=dict(color='#ab47bc', width=1, dash='dot')
                        ), row=1, col=1)
                    if 'ATR_Stop' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['ATR_Stop'], name='ATR Stop (2x)',
                            line=dict(color='#ef5350', width=1, dash='dash'),
                            fill='tonexty', fillcolor='rgba(239,83,80,0.05)'
                        ), row=1, col=1)
                    
                    # Row 2: RSI
                    if 'RSI' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['RSI'], name='RSI',
                            line=dict(color='#7e57c2', width=1.5)
                        ), row=2, col=1)
                        # Overbought/Oversold bands
                        fig.add_hline(y=70, line_dash='dash', line_color='red', opacity=0.5, row=2, col=1)
                        fig.add_hline(y=30, line_dash='dash', line_color='green', opacity=0.5, row=2, col=1)
                        fig.add_hline(y=50, line_dash='dot', line_color='gray', opacity=0.3, row=2, col=1)
                    
                    # Row 3: MACD
                    if 'MACD' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['MACD'], name='MACD',
                            line=dict(color='#42a5f5', width=1.5)
                        ), row=3, col=1)
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['MACD_Signal'], name='Signal',
                            line=dict(color='#ffa726', width=1.5)
                        ), row=3, col=1)
                        colors = ['#26a69a' if v >= 0 else '#ef5350' for v in df['MACD_Histogram']]
                        fig.add_trace(go.Bar(
                            x=df.index, y=df['MACD_Histogram'], name='Histogram',
                            marker_color=colors, opacity=0.6
                        ), row=3, col=1)
                    
                    # Row 4: OBV
                    if 'OBV' in df.columns:
                        fig.add_trace(go.Scatter(
                            x=df.index, y=df['OBV'], name='OBV',
                            line=dict(color='#66bb6a', width=1.5),
                            fill='tozeroy', fillcolor='rgba(102,187,106,0.1)'
                        ), row=4, col=1)
                    
                    fig.update_layout(
                        height=900,
                        template='plotly_dark',
                        showlegend=True,
                        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                        xaxis_rangeslider_visible=False,
                        margin=dict(l=60, r=20, t=60, b=20),
                    )
                    fig.update_yaxes(title_text='Price (₹)', row=1, col=1)
                    fig.update_yaxes(title_text='RSI', row=2, col=1, range=[0, 100])
                    fig.update_yaxes(title_text='MACD', row=3, col=1)
                    fig.update_yaxes(title_text='OBV', row=4, col=1)
                    
                    st.plotly_chart(fig, use_container_width=True)

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
                model = genai.GenerativeModel('gemini-flash-lite-latest', system_instruction=system_prompt)
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
