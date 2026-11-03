# app.py_v1.1.2

import os
import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from gspread import service_account

# ==========================================
# 1. ページ基本設定 (高密度・エンタープライズスタイル & 高視認性)
# ==========================================
st.set_page_config(
    page_title="銘柄選定精度 比較分析ダッシュボード",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=BIZ+UDGothic:wght@400;700&display=swap');

    html, body, [class*="css"], div, span, button, input {
        font-family: 'BIZ UDGothic', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        color: #111827;
        font-size: 16px !important;
    }
    
    * {
        border-radius: 0px !important;
    }
    
    .block-container {
        padding-top: 2.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 100% !important;
    }
    
    .app-header {
        background-color: #1e293b;
        color: #ffffff;
        padding: 10px 18px;
        margin-bottom: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .app-title {
        font-size: 20px !important;
        font-weight: 700;
        letter-spacing: 0.5px;
        color: #ffffff;
    }
    .app-sync-time {
        font-size: 16px !important;
        color: #cbd5e1;
    }

    .section-header {
        font-size: 18px !important;
        font-weight: 700;
        color: #111827;
        margin-bottom: 8px;
        padding-left: 8px;
        border-left: 4px solid #059669;
    }
    
    .kpi-card {
        background-color: #ffffff;
        border: 1px solid #374151;
        padding: 10px 14px;
        height: 100%;
    }
    .kpi-title {
        font-size: 16px !important;
        color: #374151;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .kpi-value-user {
        font-size: 26px !important;
        font-weight: 700;
        color: #059669;
        font-family: "Courier New", Consolas, monospace !important;
    }
    .kpi-value-bm {
        font-size: 16px !important;
        color: #6b7280;
        font-family: "Courier New", Consolas, monospace !important;
    }
    .kpi-diff {
        font-size: 16px !important;
        font-weight: 700;
        margin-top: 4px;
    }
    .diff-positive { color: #059669; }
    .diff-negative { color: #dc2626; }

    .annotation-text {
        font-size: 16px !important;
        color: #4b5563;
        font-weight: 700;
        margin-top: 6px;
        margin-bottom: 6px;
        background-color: #f3f4f6;
        padding: 6px 10px;
        border-left: 3px solid #6b7280;
    }

    .stButton > button {
        border: 1px solid #059669 !important;
        background-color: #ffffff !important;
        color: #059669 !important;
        font-weight: 700 !important;
        font-size: 16px !important;
        padding: 4px 12px !important;
        height: 38px !important;
        width: 100% !important;
    }
    .stButton > button:hover:not(:disabled) {
        background-color: #059669 !important;
        color: #ffffff !important;
    }
    .stButton > button:disabled {
        opacity: 0.4 !important;
        cursor: not-allowed !important;
        border-color: #9ca3af !important;
        color: #9ca3af !important;
        background-color: #f3f4f6 !important;
    }

    .mono-val {
        font-family: "Courier New", Consolas, monospace !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. データ取得 & 照合処理 (Notion & Google Sheets)
# ==========================================
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

@st.cache_data(ttl=300)
def load_and_process_data():
    """Notion DB (全シグナル) と スプレッドシート (実トレード) からデータを取得・照合"""
    
    # A. Notion DB から全シグナルレコードを全件取得
    raw_notion = []
    if NOTION_API_KEY and NOTION_DATABASE_ID:
        url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        has_more = True
        next_cursor = None
        
        while has_more:
            payload = {"page_size": 100}
            if next_cursor:
                payload["start_cursor"] = next_cursor
            res = requests.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                for page in data.get("results", []):
                    props = page.get("properties", {})
                    title_text = props.get("銘柄", {}).get("title", [{}])[0].get("plain_text", "")
                    code_match = title_text.split(" ")[0] if title_text else ""
                    
                    entry_date = props.get("日付", {}).get("date", {}).get("start")
                    signal = props.get("シグナル", {}).get("select", {}).get("name")
                    close_price = props.get("終値", {}).get("number")
                    stop_loss = props.get("損切り価格", {}).get("number")
                    status_val = props.get("ステータス", {}).get("status", {}).get("name") if props.get("ステータス", {}).get("status") else "未対応"
                    
                    if entry_date and code_match:
                        raw_notion.append({
                            "code": str(code_match).strip(),
                            "date": str(entry_date).strip(),
                            "signal": signal,
                            "price": close_price,
                            "stop_loss": stop_loss,
                            "status": status_val
                        })
                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")
            else:
                has_more = False

    df_raw = pd.DataFrame(raw_notion)
    if df_raw.empty:
        df_raw = pd.DataFrame(columns=["code", "date", "signal", "price", "stop_loss", "status"])

    # B. Notionシグナルのペアリング（1トレード＝1行化）
    bm_trades = []
    if not df_raw.empty:
        for code, group in df_raw.groupby("code"):
            group = group.sort_values("date")
            current = None
            for _, row in group.iterrows():
                sig = row["signal"]
                if sig in ["Long", "Short"]:
                    if current:
                        bm_trades.append(current)
                    current = {
                        "code": code,
                        "signal": sig,
                        "entry_date": row["date"],
                        "exit_date": None,
                        "entry_price": row["price"],
                        "exit_price": None,
                        "stop_loss": row["stop_loss"],
                        "status": row.get("status", "未対応"),
                        "adoption": "採用" if row.get("status") in ["注文済", "転記済", "採用"] else "見送り",
                        "return_pct": 0.0,
                        "holding_days": 0
                    }
                elif sig in ["Exit L", "Exit S"] and current:
                    current["exit_date"] = row["date"]
                    current["exit_price"] = row["price"]
                    p_in = current["entry_price"]
                    p_out = row["price"]
                    
                    if p_in and p_out and float(p_in) > 0:
                        if current["signal"] == "Long":
                            current["return_pct"] = ((float(p_out) - float(p_in)) / float(p_in)) * 100
                        else:
                            current["return_pct"] = ((float(p_in) - float(p_out)) / float(p_in)) * 100
                    
                    d_in = pd.to_datetime(current["entry_date"])
                    d_out = pd.to_datetime(row["date"])
                    current["holding_days"] = (d_out - d_in).days
                    
                    bm_trades.append(current)
                    current = None

            if current:
                bm_trades.append(current)

    df_bm = pd.DataFrame(bm_trades)
    if df_bm.empty:
        df_bm = pd.DataFrame(columns=["code", "signal", "entry_date", "exit_date", "entry_price", "exit_price", "stop_loss", "status", "adoption", "return_pct", "holding_days"])

    # C. Googleスプレッドシート（リスク管理シート）データの取得
    try:
        gc = service_account()
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet("シート1(GAS連携中)")
        records = worksheet.get_all_records()
        df_user_raw = pd.DataFrame(records)
        
        user_trades = []
        for _, row in df_user_raw.iterrows():
            e_date = str(row.get("エントリー点灯日付", row.get("entry_date", ""))).strip()
            x_date = str(row.get("消灯日付", row.get("exit_date", ""))).strip()
            x_date = x_date if x_date and x_date != "None" and x_date != "" else None
            
            p_in = row.get("想定エントリー価格", row.get("entry_price"))
            p_out = row.get("利確価格（目安）", p_in)
            code_val = str(row.get("銘柄コード", row.get("code", ""))).strip()
            
            if e_date and code_val:
                ret_pct = 0.0
                h_days = 0
                if x_date:
                    d_in = pd.to_datetime(e_date)
                    d_out = pd.to_datetime(x_date)
                    h_days = (d_out - d_in).days
                    if p_in and p_out and float(p_in) > 0:
                        ret_pct = ((float(p_out) - float(p_in)) / float(p_in)) * 100

                user_trades.append({
                    "code": code_val,
                    "signal": row.get("売買方向", row.get("signal", "Long")),
                    "entry_date": e_date,
                    "exit_date": x_date,
                    "entry_price": p_in,
                    "exit_price": p_out if x_date else None,
                    "stop_loss": row.get("損切り価格", row.get("stop_loss")),
                    "status": "転記済",
                    "adoption": "採用",
                    "return_pct": ret_pct,
                    "holding_days": h_days
                })
        df_user = pd.DataFrame(user_trades)
    except Exception as e:
        # スプレッドシート読み込み失敗時は、採用マークがついたシグナルのみをユーザーデータとして抽出（全件コピーを防止）
        df_user = df_bm[df_bm["adoption"] == "採用"].copy() if not df_bm.empty else pd.DataFrame(columns=["code", "signal", "entry_date", "exit_date", "entry_price", "exit_price", "stop_loss", "status", "adoption", "return_pct", "holding_days"])

    # 日付型の変換
    for df_item in [df_bm, df_user]:
        if not df_item.empty:
            df_item["entry_date_dt"] = pd.to_datetime(df_item["entry_date"])
            df_item["exit_date_dt"] = pd.to_datetime(df_item["exit_date"])
        else:
            df_item["entry_date_dt"] = pd.Series(dtype="datetime64[ns]")
            df_item["exit_date_dt"] = pd.Series(dtype="datetime64[ns]")

    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    fetch_time = now_jst.strftime("%Y-%m-%d %H:%M:%S JST")

    return df_bm, df_user, fetch_time


# ==========================================
# 3. メイン処理呼び出し & UIレイアウト
# ==========================================
df_bm_all, df_user_all, last_sync_time = load_and_process_data()

st.markdown(f"""
<div class="app-header">
    <div class="app-title">■ 銘柄選定評価ダッシュボード (選定アルファ検証)</div>
    <div class="app-sync-time">最終同期: {last_sync_time}</div>
</div>
""", unsafe_allow_html=True)

# 1. 期間ボタンコントロール
min_bm = df_bm_all["entry_date_dt"].min() if not df_bm_all.empty else pd.to_datetime("2026-01-01")
min_usr = df_user_all["entry_date_dt"].min() if not df_user_all.empty else pd.to_datetime("2026-01-01")
min_date = min(min_bm, min_usr).date() if pd.notnull(min_bm) and pd.notnull(min_usr) else datetime.date(2026, 1, 1)
max_date = datetime.date.today()

data_days = (max_date - min_date).days

if "selected_preset" not in st.session_state:
    st.session_state["selected_preset"] = "全期間"

b_col1, b_col2, b_col3, b_col4, f_start, f_end, f_reload = st.columns([1.5, 1.5, 1.5, 1.5, 2, 2, 1.5])

with b_col1:
    btn_1m = st.button("直近1ヶ月", disabled=(data_days < 30), use_container_width=True)
    if btn_1m: st.session_state["selected_preset"] = "直近1ヶ月"

with b_col2:
    btn_3m = st.button("直近3ヶ月", disabled=(data_days < 90), use_container_width=True)
    if btn_3m: st.session_state["selected_preset"] = "直近3ヶ月"

with b_col3:
    btn_year = st.button("今年", disabled=(data_days < 365), use_container_width=True)
    if btn_year: st.session_state["selected_preset"] = "今年"

with b_col4:
    btn_all = st.button("全期間", use_container_width=True)
    if btn_all: st.session_state["selected_preset"] = "全期間"

preset = st.session_state["selected_preset"]

if preset == "直近1ヶ月":
    start_calculated = max_date - datetime.timedelta(days=30)
elif preset == "直近3ヶ月":
    start_calculated = max_date - datetime.timedelta(days=90)
elif preset == "今年":
    start_calculated = datetime.date(2026, 1, 1)
else:
    start_calculated = min_date

start_default = max(start_calculated, min_date)

with f_start:
    start_date = st.date_input("計測開始日", value=start_default, min_value=min_date, max_value=max_date)
with f_end:
    end_date = st.date_input("計測終了日", value=max_date, min_value=min_date, max_value=max_date)
with f_reload:
    if st.button("データ再取得", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

start_dt = pd.to_datetime(start_date)
end_dt = pd.to_datetime(end_date)

df_bm = df_bm_all[(df_bm_all["entry_date_dt"] >= start_dt) & (df_bm_all["entry_date_dt"] <= end_dt)].copy()
df_user = df_user_all[(df_user_all["entry_date_dt"] >= start_dt) & (df_user_all["entry_date_dt"] <= end_dt)].copy()

# ==========================================
# 4. 指標計算ロジック
# ==========================================
def compute_metrics(df):
    if len(df) == 0:
        return {k: 0 for k in ["count", "win_rate", "avg_profit", "avg_loss", "max_profit", "max_loss", 
                               "rr_ratio", "pf", "max_dd", "max_consec_losses", "avg_hold", "avg_win_hold", "avg_loss_hold", "total_return"]}
    
    closed_df = df[df["exit_date"].notnull()].copy()
    count = len(df)
    
    if len(closed_df) == 0:
        return {k: 0 for k in ["count", "win_rate", "avg_profit", "avg_loss", "max_profit", "max_loss", 
                               "rr_ratio", "pf", "max_dd", "max_consec_losses", "avg_hold", "avg_win_hold", "avg_loss_hold", "total_return"]}
    
    wins = closed_df[closed_df["return_pct"] > 0]
    losses = closed_df[closed_df["return_pct"] <= 0]
    
    win_rate = (len(wins) / len(closed_df)) * 100
    avg_profit = wins["return_pct"].mean() if len(wins) > 0 else 0.0
    avg_loss = losses["return_pct"].mean() if len(losses) > 0 else 0.0
    max_profit = closed_df["return_pct"].max()
    max_loss = closed_df["return_pct"].min()
    
    rr_ratio = (avg_profit / abs(avg_loss)) if avg_loss != 0 else 0.0
    
    total_p = wins["return_pct"].sum()
    total_l = abs(losses["return_pct"].sum())
    pf = (total_p / total_l) if total_l != 0 else 0.0
    
    df_sorted = closed_df.sort_values("exit_date_dt")
    cum_returns = df_sorted["return_pct"].cumsum()
    peak = cum_returns.cummax()
    dd = cum_returns - peak
    max_dd = dd.min() if len(dd) > 0 else 0.0
    
    is_loss = (df_sorted["return_pct"] <= 0).astype(int)
    max_consec_losses = (is_loss.groupby((is_loss != is_loss.shift()).cumsum()).cumsum()).max() if len(is_loss) > 0 else 0
    
    avg_hold = closed_df["holding_days"].mean()
    avg_win_hold = wins["holding_days"].mean() if len(wins) > 0 else 0.0
    avg_loss_hold = losses["holding_days"].mean() if len(losses) > 0 else 0.0
    
    return {
        "count": count,
        "win_rate": win_rate,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "rr_ratio": rr_ratio,
        "pf": pf,
        "max_dd": max_dd,
        "max_consec_losses": max_consec_losses,
        "avg_hold": avg_hold,
        "avg_win_hold": avg_win_hold,
        "avg_loss_hold": avg_loss_hold,
        "total_return": cum_returns.iloc[-1] if len(cum_returns) > 0 else 0.0
    }

m_bm = compute_metrics(df_bm)
m_user = compute_metrics(df_user)

# ==========================================
# 5. 上部 コアKPI サマリーカード
# ==========================================
k1, k2, k3, k4 = st.columns(4)

with k1:
    alpha_ret = m_user["total_return"] - m_bm["total_return"]
    diff_class = "diff-positive" if alpha_ret >= 0 else "diff-negative"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">通算損益率 (Alpha)</div>
        <div class="kpi-value-user">{m_user['total_return']:+.1f}%</div>
        <div class="kpi-value-bm">全体: {m_bm['total_return']:+.1f}%</div>
        <div class="kpi-diff {diff_class}">選定効果: {alpha_ret:+.1f}%</div>
    </div>
    """, unsafe_allow_html=True)

with k2:
    diff_wr = m_user["win_rate"] - m_bm["win_rate"]
    diff_class = "diff-positive" if diff_wr >= 0 else "diff-negative"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">勝率 (Win Rate)</div>
        <div class="kpi-value-user">{m_user['win_rate']:.1f}%</div>
        <div class="kpi-value-bm">全体: {m_bm['win_rate']:.1f}%</div>
        <div class="kpi-diff {diff_class}">差分: {diff_wr:+.1f}% pt</div>
    </div>
    """, unsafe_allow_html=True)

with k3:
    diff_pf = m_user["pf"] - m_bm["pf"]
    diff_class = "diff-positive" if diff_pf >= 0 else "diff-negative"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">プロフィットファクター (PF)</div>
        <div class="kpi-value-user">{m_user['pf']:.2f}</div>
        <div class="kpi-value-bm">全体: {m_bm['pf']:.2f}</div>
        <div class="kpi-diff {diff_class}">差分: {diff_pf:+.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with k4:
    diff_rr = m_user["rr_ratio"] - m_bm["rr_ratio"]
    diff_class = "diff-positive" if diff_rr >= 0 else "diff-negative"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-title">リスクリワード比 (R/R)</div>
        <div class="kpi-value-user">{m_user['rr_ratio']:.2f}</div>
        <div class="kpi-value-bm">全体: {m_bm['rr_ratio']:.2f}</div>
        <div class="kpi-diff {diff_class}">差分: {diff_rr:+.2f}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 14px;'></div>", unsafe_allow_html=True)

# ==========================================
# 6. メイン分析エリア (左: 折れ線チャート / 右: 深掘り比較テーブル)
# ==========================================
chart_col, table_col = st.columns([7, 5])

with chart_col:
    st.markdown('<div class="section-header">■ 累積損益率推移 (%)</div>', unsafe_allow_html=True)
    
    date_range = pd.date_range(start=start_dt, end=end_dt, freq="D")
    df_time = pd.DataFrame({"date": date_range})
    
    def get_cum_series(trade_df, dates):
        res = []
        if trade_df.empty:
            return [0.0] * len(dates)
        closed_df = trade_df[trade_df["exit_date"].notnull()].copy()
        for d in dates:
            sub = closed_df[closed_df["exit_date_dt"] <= d]
            res.append(sub["return_pct"].sum() if len(sub) > 0 else 0.0)
        return res

    df_time["BM"] = get_cum_series(df_bm, df_time["date"])
    df_time["USER"] = get_cum_series(df_user, df_time["date"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_time["date"], y=df_time["BM"],
        mode="lines", name="全シグナル (ベンチマーク)",
        line=dict(color="#6b7280", width=1.8, dash="dash")
    ))
    fig.add_trace(go.Scatter(
        x=df_time["date"], y=df_time["USER"],
        mode="lines", name="リスク管理シート (選定後)",
        line=dict(color="#059669", width=2.8)
    ))

    fig.update_layout(
        margin=dict(l=40, r=20, t=15, b=30),
        height=360,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=16)),
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb", zeroline=False, tickfont=dict(size=14)),
        yaxis=dict(showgrid=True, gridcolor="#e5e7eb", zeroline=True, zerolinecolor="#111827", zerolinewidth=1, tickfont=dict(size=14)),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff"
    )
    st.plotly_chart(fig, use_container_width=True)

with table_col:
    st.markdown('<div class="section-header">■ 深掘り指標比較 (全13項目 ＋ 選定差分)</div>', unsafe_allow_html=True)
    
    metrics_data = [
        {"指標名": "トレード回数", "全シグナル(BM)": f"{m_bm['count']} 件", "リスク管理シート": f"{m_user['count']} 件", "選定差分 (Diff)": f"{m_user['count'] - m_bm['count']} 件"},
        {"指標名": "勝率 [%]", "全シグナル(BM)": f"{m_bm['win_rate']:.1f}%", "リスク管理シート": f"{m_user['win_rate']:.1f}%", "選定差分 (Diff)": f"{m_user['win_rate'] - m_bm['win_rate']:+.1f}% pt"},
        {"指標名": "平均利益 [%]", "全シグナル(BM)": f"{m_bm['avg_profit']:+.2f}%", "リスク管理シート": f"{m_user['avg_profit']:+.2f}%", "選定差分 (Diff)": f"{m_user['avg_profit'] - m_bm['avg_profit']:+.2f}%"},
        {"指標名": "平均損失 [%]", "全シグナル(BM)": f"{m_bm['avg_loss']:+.2f}%", "リスク管理シート": f"{m_user['avg_loss']:+.2f}%", "選定差分 (Diff)": f"{m_user['avg_loss'] - m_bm['avg_loss']:+.2f}%"},
        {"指標名": "最大利益 [%]", "全シグナル(BM)": f"{m_bm['max_profit']:+.2f}%", "リスク管理シート": f"{m_user['max_profit']:+.2f}%", "選定差分 (Diff)": f"{m_user['max_profit'] - m_bm['max_profit']:+.2f}%"},
        {"指標名": "最大損失 [%]", "全シグナル(BM)": f"{m_bm['max_loss']:+.2f}%", "リスク管理シート": f"{m_user['max_loss']:+.2f}%", "選定差分 (Diff)": f"{m_user['max_loss'] - m_bm['max_loss']:+.2f}%"},
        {"指標名": "リスクリワード比", "全シグナル(BM)": f"{m_bm['rr_ratio']:.2f}", "リスク管理シート": f"{m_user['rr_ratio']:.2f}", "選定差分 (Diff)": f"{m_user['rr_ratio'] - m_bm['rr_ratio']:+.2f}"},
        {"指標名": "プロフィットファクター", "全シグナル(BM)": f"{m_bm['pf']:.2f}", "リスク管理シート": f"{m_user['pf']:.2f}", "選定差分 (Diff)": f"{m_user['pf'] - m_bm['pf']:+.2f}"},
        {"指標名": "最大ドローダウン [%]", "全シグナル(BM)": f"{m_bm['max_dd']:.1f}%", "リスク管理シート": f"{m_user['max_dd']:.1f}%", "選定差分 (Diff)": f"{m_user['max_dd'] - m_bm['max_dd']:.1f}% pt"},
        {"指標名": "最大連敗数", "全シグナル(BM)": f"{m_bm['max_consec_losses']} 連敗", "リスク管理シート": f"{m_user['max_consec_losses']} 連敗", "選定差分 (Diff)": f"{m_user['max_consec_losses'] - m_bm['max_consec_losses']} 連敗"},
        {"指標名": "平均保有日数", "全シグナル(BM)": f"{m_bm['avg_hold']:.1f} 日", "リスク管理シート": f"{m_user['avg_hold']:.1f} 日", "選定差分 (Diff)": f"{m_user['avg_hold'] - m_bm['avg_hold']:+.1f} 日"},
        {"指標名": "平均含み益保有日数", "全シグナル(BM)": f"{m_bm['avg_win_hold']:.1f} 日", "リスク管理シート": f"{m_user['avg_win_hold']:.1f} 日", "選定差分 (Diff)": f"{m_user['avg_win_hold'] - m_bm['avg_win_hold']:+.1f} 日"},
        {"指標名": "平均含み損保有日数", "全シグナル(BM)": f"{m_bm['avg_loss_hold']:.1f} 日", "リスク管理シート": f"{m_user['avg_loss_hold']:.1f} 日", "選定差分 (Diff)": f"{m_user['avg_loss_hold'] - m_bm['avg_loss_hold']:+.1f} 日"}
    ]
    
    df_metrics = pd.DataFrame(metrics_data)
    
    table_html = "<table style='width:100%; font-size:16px; border-collapse:collapse; border:1px solid #374151; text-align:right;'>"
    table_html += "<tr style='background-color:#e2e8f0; font-weight:bold; border-bottom:2px solid #1e293b;'><th style='text-align:left; padding:6px 8px;'>指標名</th><th style='padding:6px 8px;'>全シグナル(BM)</th><th style='padding:6px 8px;'>リスク管理シート</th><th style='padding:6px 8px;'>選定差分 (Diff)</th></tr>"
    
    for idx, row in df_metrics.iterrows():
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        table_html += f"<tr style='background-color:{bg}; border-bottom:1px solid #cbd5e1; height:28px;'>"
        table_html += f"<td style='text-align:left; padding:4px 8px; font-weight:700;'>{row['指標名']}</td>"
        table_html += f"<td style='padding:4px 8px;' class='mono-val'>{row['全シグナル(BM)']}</td>"
        table_html += f"<td style='padding:4px 8px; font-weight:bold; color:#059669;' class='mono-val'>{row['リスク管理シート']}</td>"
        table_html += f"<td style='padding:4px 8px;' class='mono-val'>{row['選定差分 (Diff)']}</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    st.markdown(table_html, unsafe_allow_html=True)
    st.markdown('<div class="annotation-text">※「トレード回数」には、手仕舞い前（ポジション保有中）のトレードも含まれます。</div>', unsafe_allow_html=True)

# ==========================================
# 7. 個別トレード照合データグリッド (採用・見送り判定カラムの復元)
# ==========================================
st.markdown("<hr style='margin: 20px 0 16px 0; border: none; border-top: 1px solid #9ca3af;'>", unsafe_allow_html=True)
st.markdown('<div class="section-header">■ 個別トレードログ (全照合データ)</div>', unsafe_allow_html=True)

if not df_bm.empty:
    df_display = df_bm[["entry_date", "exit_date", "code", "signal", "adoption", "entry_price", "exit_price", "stop_loss", "return_pct", "holding_days"]].copy()

    df_display["entry_date"] = df_display["entry_date"].astype(str)
    df_display["exit_date"] = df_display["exit_date"].apply(lambda x: str(x) if pd.notnull(x) and str(x) != "None" else "保有中(未決済)")
    df_display["return_pct"] = df_display.apply(lambda r: f"{r['return_pct']:+.2f}%" if r["exit_date"] != "保有中(未決済)" else "保有中(未決済)", axis=1)
    df_display["entry_price"] = df_display["entry_price"].map(lambda x: f"{x:,.0f} 円" if pd.notnull(x) else "-")
    df_display["exit_price"] = df_display["exit_price"].map(lambda x: f"{x:,.0f} 円" if pd.notnull(x) and str(x) != "None" else "-")
    
    df_display = df_display.rename(columns={
        "entry_date": "エントリー日付",
        "exit_date": "手仕舞い日付",
        "code": "銘柄コード",
        "signal": "シグナル",
        "adoption": "判定(採用/見送り)",
        "entry_price": "エントリー価格",
        "exit_price": "手仕舞い価格",
        "stop_loss": "損切り価格",
        "return_pct": "確定損益率",
        "holding_days": "保有日数"
    })
else:
    df_display = pd.DataFrame(columns=["エントリー日付", "手仕舞い日付", "銘柄コード", "シグナル", "判定(採用/見送り)", "エントリー価格", "手仕舞い価格", "損切り価格", "確定損益率", "保有日数"])

st.dataframe(
    df_display.sort_values("エントリー日付", ascending=False),
    use_container_width=True,
    hide_index=True,
    height=400
)
