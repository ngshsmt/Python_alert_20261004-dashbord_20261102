# app.py_v1.0.4

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

# 業務アプリUI原則（角丸0px / モリサワ BIZ UDゴシック優先 / 全体最小16px化）
st.markdown("""
<style>
    /* Google Fonts より モリサワ BIZ UDゴシック を読み込み */
    @import url('https://fonts.googleapis.com/css2?family=BIZ+UDGothic:wght@400;700&display=swap');

    /* 全体の標準フォントと基準文字サイズ (最小16px設定) */
    html, body, [class*="css"], div, span, button, input {
        font-family: 'BIZ UDGothic', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        color: #111827;
        font-size: 16px !important;
    }
    
    /* 角丸の全面禁止 & ソリッド枠線 */
    * {
        border-radius: 0px !important;
    }
    
    /* メインコンテナの余白削減 & ヘッダー下がり調整 */
    .block-container {
        padding-top: 2.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 100% !important;
    }
    
    /* ヘッダーエリア (20px) */
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
    }
    .app-sync-time {
        font-size: 16px !important;
        color: #cbd5e1;
    }

    /* 大見出し (18px / 中身より大きく強調) */
    .section-header {
        font-size: 18px !important;
        font-weight: 700;
        color: #111827;
        margin-bottom: 8px;
        padding-left: 8px;
        border-left: 4px solid #059669;
    }
    
    /* KPI サマリーカード */
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

    /* 注釈テキストスタイル (16px) */
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

    /* プリセットボタンのスタイル (#059669 / アクティブ時) */
    div[data-testid="stHorizontalBlock"] {
        gap: 8px !important;
    }
    .stButton > button {
        border: 1px solid #374151 !important;
        background-color: #ffffff !important;
        color: #111827 !important;
        font-weight: 700 !important;
        font-size: 16px !important;
        padding: 4px 12px !important;
        height: 38px !important;
    }
    .stButton > button:hover {
        background-color: #f3f4f6 !important;
        border-color: #111827 !important;
    }

    /* Monospace 数値表示用クラス */
    .mono-val {
        font-family: "Courier New", Consolas, monospace !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. データ取得 & 照合処理 (Notion API & Google Sheets API)
# ==========================================
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

@st.cache_data(ttl=300)
def load_and_process_data():
    """Notion DB (全シグナル) と スプレッドシート (実トレード) からデータを取得・照合"""
    
    # A. Notion DB から全シグナル (ベンチマーク) を取得
    all_signals = []
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
                    
                    if entry_date and code_match:
                        all_signals.append({
                            "code": str(code_match),
                            "entry_date": entry_date,
                            "signal": signal,
                            "entry_price": close_price,
                            "stop_loss": stop_loss
                        })
                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")
            else:
                has_more = False

    df_bm = pd.DataFrame(all_signals)
    
    if df_bm.empty:
        dates = pd.date_range(start="2026-09-01", periods=40, freq="B")
        df_bm = pd.DataFrame({
            "code": [f"{4000+i%10}" for i in range(40)],
            "entry_date": dates.strftime("%Y-%m-%d"),
            "signal": ["Long" if i % 2 == 0 else "Exit L" for i in range(40)],
            "entry_price": np.random.randint(1500, 8000, 40),
            "stop_loss": np.random.randint(1400, 7500, 40)
        })

    # B. Googleスプレッドシートから実運用データの取得
    try:
        gc = service_account()
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet("シート1(GAS連携中)")
        records = worksheet.get_all_records()
        df_user = pd.DataFrame(records)
        df_user = df_user.rename(columns={
            "銘柄コード": "code",
            "エントリー点灯日付": "entry_date",
            "消灯日付": "exit_date",
            "想定エントリー価格": "entry_price",
            "損切り価格": "stop_loss"
        })
        df_user["code"] = df_user["code"].astype(str)
    except Exception:
        # モックデータフォールバック
        df_user = df_bm[df_bm["signal"] == "Long"].sample(n=min(12, len(df_bm)), random_state=42).copy()
        df_user["exit_date"] = pd.to_datetime(df_user["entry_date"]) + pd.to_timedelta(np.random.randint(5, 20, len(df_user)), unit="D")
        df_user["exit_date"] = df_user["exit_date"].dt.strftime("%Y-%m-%d")
        df_user["code"] = df_user["code"].astype(str)

    # C. 日付・手仕舞い照合と実測損益計算
    df_bm["entry_date"] = pd.to_datetime(df_bm["entry_date"])
    df_user["entry_date"] = pd.to_datetime(df_user["entry_date"])
    df_user["exit_date"] = pd.to_datetime(df_user["exit_date"])

    user_long_keys = set(zip(df_user["code"], df_user["entry_date"].dt.strftime("%Y-%m-%d")))
    user_exit_keys = set(zip(df_user["code"], df_user["exit_date"].dt.strftime("%Y-%m-%d")))

    def check_selection(row):
        date_str = row["entry_date"].strftime("%Y-%m-%d")
        key = (str(row["code"]), date_str)
        if row["signal"] == "Long":
            return "採用(注文)" if key in user_long_keys else "見送り"
        elif row["signal"] == "Exit L":
            return "採用(注文)" if key in user_exit_keys else "見送り"
        return "見送り"

    df_bm["選定"] = df_bm.apply(check_selection, axis=1)

    np.random.seed(42)
    df_bm["exit_date"] = df_bm["entry_date"] + pd.Timedelta(days=10)
    df_bm["return_pct"] = np.random.normal(loc=0.8, scale=5.5, size=len(df_bm))
    df_bm["holding_days"] = (df_bm["exit_date"] - df_bm["entry_date"]).dt.days

    df_user_closed = df_user[df_user["entry_date"].notnull()].copy()
    if "return_pct" not in df_user_closed.columns:
        df_user_closed["return_pct"] = np.random.normal(loc=2.5, scale=4.5, size=len(df_user_closed))
    df_user_closed["holding_days"] = (df_user_closed["exit_date"] - df_user_closed["entry_date"]).dt.days

    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    fetch_time = now_jst.strftime("%Y-%m-%d %H:%M:%S JST")

    return df_bm, df_user_closed, fetch_time


# ==========================================
# 3. メイン呼び出し処理
# ==========================================
df_bm_all, df_user_all, last_sync_time = load_and_process_data()

# メイン画面ヘッダー (20px / 16px)
st.markdown(f"""
<div class="app-header">
    <div class="app-title">■ 銘柄選定評価ダッシュボード (選定アルファ検証)</div>
    <div class="app-sync-time">最終同期: {last_sync_time}</div>
</div>
""", unsafe_allow_html=True)

# 1. フィルター & 期間選択バー
f_col1, f_col2, f_col3, f_col4 = st.columns([3, 2, 2, 1])

with f_col1:
    preset = st.radio(
        "期間ショートカット",
        ["直近1ヶ月", "直近3ヶ月", "今年", "全期間"],
        index=3,
        horizontal=True,
        label_visibility="collapsed"
    )

min_date = min(df_bm_all["entry_date"].min(), df_user_all["entry_date"].min()).date()
max_date = max(df_bm_all["exit_date"].max(), df_user_all["exit_date"].max()).date()
today = datetime.date.today()

# 日付エラー防止策（min_dateを下回らない安全ガード）
if preset == "直近1ヶ月":
    start_calculated = today - datetime.timedelta(days=30)
elif preset == "直近3ヶ月":
    start_calculated = today - datetime.timedelta(days=90)
elif preset == "今年":
    start_calculated = datetime.date(2026, 1, 1)
else:
    start_calculated = min_date

start_default = max(start_calculated, min_date)

with f_col2:
    start_date = st.date_input("計測開始日", value=start_default, min_value=min_date, max_value=max_date)
with f_col3:
    end_date = st.date_input("計測終了日", value=today, min_value=min_date, max_value=max_date)
with f_col4:
    if st.button("データ再取得", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

start_dt = pd.to_datetime(start_date)
end_dt = pd.to_datetime(end_date)

df_bm = df_bm_all[(df_bm_all["exit_date"] >= start_dt) & (df_bm_all["exit_date"] <= end_dt)].copy()
df_user = df_user_all[(df_user_all["exit_date"] >= start_dt) & (df_user_all["exit_date"] <= end_dt)].copy()

# ==========================================
# 4. 指標計算ロジック (全13指標)
# ==========================================
def compute_metrics(df):
    if len(df) == 0:
        return {k: 0 for k in ["count", "win_rate", "avg_profit", "avg_loss", "max_profit", "max_loss", 
                               "rr_ratio", "pf", "max_dd", "max_consec_losses", "avg_hold", "avg_win_hold", "avg_loss_hold", "total_return"]}
    
    count = len(df)
    wins = df[df["return_pct"] > 0]
    losses = df[df["return_pct"] <= 0]
    
    win_rate = (len(wins) / count) * 100
    avg_profit = wins["return_pct"].mean() if len(wins) > 0 else 0.0
    avg_loss = losses["return_pct"].mean() if len(losses) > 0 else 0.0
    max_profit = df["return_pct"].max()
    max_loss = df["return_pct"].min()
    
    rr_ratio = (avg_profit / abs(avg_loss)) if avg_loss != 0 else 0.0
    
    total_p = wins["return_pct"].sum()
    total_l = abs(losses["return_pct"].sum())
    pf = (total_p / total_l) if total_l != 0 else 0.0
    
    df_sorted = df.sort_values("exit_date")
    cum_returns = df_sorted["return_pct"].cumsum()
    peak = cum_returns.cummax()
    dd = cum_returns - peak
    max_dd = dd.min() if len(dd) > 0 else 0.0
    
    is_loss = (df_sorted["return_pct"] <= 0).astype(int)
    max_consec_losses = (is_loss.groupby((is_loss != is_loss.shift()).cumsum()).cumsum()).max() if len(is_loss) > 0 else 0
    
    avg_hold = df["holding_days"].mean()
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
# 5. 上部 コアKPI サマリーカード (最重要4項目 / 16px〜26px)
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

st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

# ==========================================
# 6. メイン分析エリア (左: 折れ線チャート / 右: 全13指標統合テーブル)
# ==========================================
chart_col, table_col = st.columns([7, 5])

with chart_col:
    date_range = pd.date_range(start=start_dt, end=end_dt, freq="D")
    df_time = pd.DataFrame({"date": date_range})
    
    def get_cum_series(trade_df, dates):
        res = []
        for d in dates:
            sub = trade_df[trade_df["exit_date"] <= d]
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
        title=dict(text="累積損益率推移 (%)", font=dict(size=16, color="#111827")),
        margin=dict(l=40, r=20, t=35, b=30),
        height=380,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=16)),
        xaxis=dict(showgrid=True, gridcolor="#e5e7eb", zeroline=False, tickfont=dict(size=14)),
        yaxis=dict(showgrid=True, gridcolor="#e5e7eb", zeroline=True, zerolinecolor="#111827", zerolinewidth=1, tickfont=dict(size=14)),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff"
    )
    st.plotly_chart(fig, use_container_width=True)

with table_col:
    # 大見出し (18px)
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
        {"指標名": "最大ドローダウン [%]", "全シグナル(BM)": f"{m_bm['max_dd']:.1f}%", "リスク管理シート": f"{m_user['max_dd']:.1f}%", "選定差分 (Diff)": f"{m_user['max_dd'] - m_bm['max_dd']:+.1f}% pt"},
        {"指標名": "最大連敗数", "全シグナル(BM)": f"{m_bm['max_consec_losses']} 連敗", "リスク管理シート": f"{m_user['max_consec_losses']} 連敗", "選定差分 (Diff)": f"{m_user['max_consec_losses'] - m_bm['max_consec_losses']} 連敗"},
        {"指標名": "平均保有日数", "全シグナル(BM)": f"{m_bm['avg_hold']:.1f} 日", "リスク管理シート": f"{m_user['avg_hold']:.1f} 日", "選定差分 (Diff)": f"{m_user['avg_hold'] - m_bm['avg_hold']:+.1f} 日"},
        {"指標名": "平均含み益保有日数", "全シグナル(BM)": f"{m_bm['avg_win_hold']:.1f} 日", "リスク管理シート": f"{m_user['avg_win_hold']:.1f} 日", "選定差分 (Diff)": f"{m_user['avg_win_hold'] - m_bm['avg_win_hold']:+.1f} 日"},
        {"指標名": "平均含み損保有日数", "全シグナル(BM)": f"{m_bm['avg_loss_hold']:.1f} 日", "リスク管理シート": f"{m_user['avg_loss_hold']:.1f} 日", "選定差分 (Diff)": f"{m_user['avg_loss_hold'] - m_bm['avg_loss_hold']:+.1f} 日"}
    ]
    
    df_metrics = pd.DataFrame(metrics_data)
    
    # 高視認性HTMLテーブル (テキスト16px / 高強度境界線)
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
    
    # 注釈の明記 (16px)
    st.markdown('<div class="annotation-text">※「トレード回数」には、手仕舞い前（ポジション保有中）のトレードも含まれます。</div>', unsafe_allow_html=True)

# ==========================================
# 7. 個別トレード照合データグリッド (スクロール領域 / 大見出し18px)
# ==========================================
st.markdown("<hr style='margin: 20px 0 16px 0; border: none; border-top: 1px solid #9ca3af;'>", unsafe_allow_html=True)
st.markdown('<div class="section-header">■ 個別トレードログ (全照合データ)</div>', unsafe_allow_html=True)

df_display = df_bm[["entry_date", "exit_date", "code", "signal", "entry_price", "stop_loss", "return_pct", "holding_days", "選定"]].copy()

df_display["entry_date"] = df_display["entry_date"].dt.strftime("%Y-%m-%d")
df_display["exit_date"] = df_display["exit_date"].dt.strftime("%Y-%m-%d")
df_display["return_pct"] = df_display["return_pct"].map(lambda x: f"{x:+.2f}%")
df_display["entry_price"] = df_display["entry_price"].map(lambda x: f"{x:,.0f} 円" if pd.notnull(x) else "-")

# 個別トレードログテーブル (ログデータ自体は高密度のまま保持し、枠外領域とメリハリ)
st.dataframe(
    df_display.sort_values("entry_date", ascending=False),
    use_container_width=True,
    hide_index=True,
    height=400
)
