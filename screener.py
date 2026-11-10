# Pythonメインスクリプト（screener.py）_1.0.6

import datetime
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ==========================================
# 1. 環境変数・設定値の読み込み
# ==========================================
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
MAIL_TO = os.environ.get("MAIL_TO")

# ==========================================
# 2. TradingView互換 RMA & Supertrend計算ロジック
# ==========================================
def calculate_rma(series, period):
    """TradingView ta.rma (Wilder's Smoothing) と完全互換の計算"""
    rma = np.full(len(series), np.nan)
    vals = series.values
    if len(vals) < period:
        return pd.Series(rma, index=series.index)
    
    # 最初はSMAで初期化
    rma[period - 1] = np.mean(vals[:period])
    alpha = 1.0 / period
    for i in range(period, len(vals)):
        rma[i] = alpha * vals[i] + (1.0 - alpha) * rma[i - 1]
    return pd.Series(rma, index=series.index)

def calculate_supertrend(df, period=10, multiplier=3.0):
    """TradingView ta.supertrend と完全互換の計算 (direction: -1=Buy, 1=Sell)"""
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # True Range の計算
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # RMAによるATR計算 (TradingView ta.atr 準拠)_Upper / Lower Band の計算
    atr = calculate_rma(tr, period)

    hl2 = (high + low) / 2
    basic_ub = hl2 + (multiplier * atr)
    basic_lb = hl2 - (multiplier * atr)

    final_ub = np.full(len(df), np.nan)
    final_lb = np.full(len(df), np.nan)
    st_dir = np.full(len(df), 1) # 初期値 1 (Sell)

    # 最初の有効インデックスを取得
    first_valid_idx = period - 1
    if first_valid_idx >= len(df):
        return pd.Series(st_dir, index=df.index), pd.Series(final_ub, index=df.index)

    # 初期設定
    final_ub[first_valid_idx] = basic_ub.iloc[first_valid_idx]
    final_lb[first_valid_idx] = basic_lb.iloc[first_valid_idx]
    st_dir[first_valid_idx] = -1 if close.iloc[first_valid_idx] > final_ub[first_valid_idx] else 1

    for i in range(first_valid_idx + 1, len(df)):
        # Upper Band 更新
        if basic_ub.iloc[i] < final_ub[i-1] or close.iloc[i-1] > final_ub[i-1]:
            final_ub[i] = basic_ub.iloc[i]
        else:
            final_ub[i] = final_ub[i-1]

        # Lower Band 更新
        if basic_lb.iloc[i] > final_lb[i-1] or close.iloc[i-1] < final_lb[i-1]:
            final_lb[i] = basic_lb.iloc[i]
        else:
            final_lb[i] = final_lb[i-1]

        # Direction 判定 (-1: Buy, 1: Sell)
        prev_dir = st_dir[i-1]
        if prev_dir == -1:
            if close.iloc[i] < final_lb[i]:
                st_dir[i] = 1 # Sellへ転換
            else:
                st_dir[i] = -1 # Buy継続
        else:
            if close.iloc[i] > final_ub[i]:
                st_dir[i] = -1 # Buyへ転換
            else:
                st_dir[i] = 1 # Sell継続

    st_val = np.where(st_dir == -1, final_lb, final_ub)
    return pd.Series(st_dir, index=df.index), pd.Series(st_val, index=df.index)
    
# ==========================================
# 3. Notion過去ステータス照合関数
# ==========================================  
def get_latest_signal_from_notion(code):
    # Notion DBから対象銘柄の最新レコードのシグナルを取得する
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        return None

    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # 銘柄コードでフィルタリングし、日付降順で最新1件を取得
    payload = {
        "filter": {
            "property": "銘柄",
            "title": {
                "starts_with": code
            }
        },
        "sorts": [
            {
                "property": "日付",
                "direction": "descending"
            }
        ],
        "page_size": 1
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200:
            results = res.json().get("results", [])
            if results:
                props = results[0].get("properties", {})
                signal_prop = props.get("シグナル", {}).get("select")
                if signal_prop:
                    return signal_prop.get("name")
    except Exception as e:
        print(f"Error querying Notion for {code}: {e}")
    
    return None

# ==========================================
# 4. テクニカル指標計算 & シグナル判定関数
# ==========================================
def analyze_ticker(ticker_symbol):
    try:
        # ウォームアップ確保のため300日分取得
        df = yf.download(ticker_symbol, period="300d", interval="1d", progress=False)
        if df.empty or len(df) < 100:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close']

        # 移動平均線
        df['SMA5'] = close.rolling(window=5).mean()
        df['SMA10'] = close.rolling(window=10).mean()
        df['SMA20'] = close.rolling(window=20).mean()
        df['SMA50'] = close.rolling(window=50).mean()

        # Supertrend (10, 3.0)
        df['ST_Direction'], df['ST_Value'] = calculate_supertrend(df, period=10, multiplier=3.0)

        # Supertrend Buy判定 (TradingView: direction < 0)
        df['isStBuy'] = df['ST_Direction'] == -1

        # パーフェクトオーダー条件
        df['isSimplePO'] = (df['SMA5'] > df['SMA10']) & (df['SMA10'] > df['SMA20']) & (close > df['SMA50'])

        # トラッキング条件
        # TradingView: ta.change(stDirection) < 0 (1 -> -1 への転換 = change -2)
        df['st_turn_buy'] = (df['ST_Direction'].shift(1) == 1) & (df['ST_Direction'] == -1)
        # TradingView: ta.crossover(sma5, sma10)
        df['sma_cross'] = (df['SMA5'].shift(1) <= df['SMA10'].shift(1)) & (df['SMA5'] > df['SMA10'])

        # 買いエントリー条件
        df['longEntryCond'] = df['isStBuy'] & df['isSimplePO'] & (df['st_turn_buy'] | df['sma_cross'])
        # 買い手仕舞い条件
        df['longExitCond'] = (df['SMA5'] < df['SMA20']) | (~df['isStBuy'])
        
        # 空売り拡張用ダミー（現在は常に False）
        df['shortEntryCond'] = False
        df['shortExitCond'] = False
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        code = ticker_symbol.replace(".T", "")
        raw_signal = None
        if latest['longEntryCond']:
            raw_signal = "Long"
        elif latest['longExitCond'] and prev['isStBuy']:
            raw_signal = "Exit L"
        elif latest['shortEntryCond']:
            raw_signal = "Short"
        elif latest['shortExitCond']:
            raw_signal = "Exit S"

        # Notionの過去ステータスと照合して一対化（交互化）を強制
        final_signal = None
        if raw_signal:
            latest_notion_signal = get_latest_signal_from_notion(code)

            if raw_signal == "Long":
                # 直近が Long でない場合のみ Long を許可 (ノーポジションまたは Exit L / Exit S / Short からの転換)
                if latest_notion_signal != "Long":
                    final_signal = "Long"
                else:
                    print(f"Skip Long for {code}: Already in LONG position.")
            elif raw_signal == "Exit L":
                # 直近が Long の場合のみ Exit L を許可
                if latest_notion_signal == "Long":
                    final_signal = "Exit L"
                else:
                    print(f"Skip Exit L for {code}: No active LONG position.")
            elif raw_signal == "Short":
                # 直近が Short でない場合のみ Short を許可
                if latest_notion_signal != "Short":
                    final_signal = "Short"
                else:
                    print(f"Skip Short for {code}: Already in SHORT position.")
            elif raw_signal == "Exit S":
                # 直近が Short の場合のみ Exit S を許可
                if latest_notion_signal == "Short":
                    final_signal = "Exit S"
                else:
                    print(f"Skip Exit S for {code}: No active SHORT position.")
                    
        return {
            "symbol": ticker_symbol,
            "code": code,
            "close": float(latest['Close']),
            "st_val": float(latest['ST_Value']),
            "signal": final_signal
        }
    except Exception as e:
        print(f"Error processing {ticker_symbol}: {e}")
        return None

# ==========================================
# 5. Notion DB登録関数
# ==========================================
def push_to_notion(result_data, company_name=""):
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        print("Notion API credentials not provided. Skipping Notion push.")
        return

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    today_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    title_text = f"{result_data['code']} {company_name}".strip()

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "銘柄": {"title": [{"text": {"content": title_text}}]},
            "日付": {"date": {"start": today_str}},
            "シグナル": {"select": {"name": result_data['signal']}},
            "終値": {"number": result_data['close']},
            "ステータス": {"status": {"name": "未対応"}},
            "想定損切り価格": {"number": result_data['st_val']}
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    if res.status_code != 200:
        print(f"Failed to push to Notion: {res.text}")

# ==========================================
# 6. メール送信関数
# ==========================================
def send_email(signals_dict):
    if not SMTP_USER or not SMTP_PASS or not MAIL_TO:
        print("SMTP credentials not provided. Skipping email dispatch.")
        return

    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    date_str = now_jst.strftime("%Y/%m/%d")
    weekday_str = weekdays_jp[now_jst.weekday()]

    subject = f"{date_str}({weekday_str})の対象銘柄コード"

    long_list = "\n".join(signals_dict["Long"]) if signals_dict["Long"] else ""
    short_list = "\n".join(signals_dict["Short"]) if signals_dict["Short"] else ""
    exit_l_list = "\n".join(signals_dict["Exit L"]) if signals_dict["Exit L"] else ""
    exit_s_list = "\n".join(signals_dict["Exit S"]) if signals_dict["Exit S"] else ""

    body = f"""①エントリー
【買い】
{long_list}

【空売り】
{short_list}

②手仕舞い
【買い】
{exit_l_list}

【空売り】
{exit_s_list}"""

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")

# ==========================================
# 7. メイン実行フロー
# ==========================================
def main():
    csv_path = "watchlist_20261004.csv"
    if not os.path.exists(csv_path):
        print(f"{csv_path} not found.")
        return

    df_watchlist = pd.read_csv(csv_path)
    code_col = 'code' if 'code' in df_watchlist.columns else df_watchlist.columns[0]
    codes = df_watchlist[code_col].astype(str).tolist()

    signals_summary = {
        "Long": [],
        "Short": [],
        "Exit L": [],
        "Exit S": []
    }

    print(f"Starting analysis for {len(codes)} stocks...")

    for code in codes:
        ticker = code if code.endswith(".T") else f"{code}.T"
        res = analyze_ticker(ticker)

        if res and res['signal']:
            print(f"Signal detected: {res['code']} -> {res['signal']}")
            push_to_notion(res)
            if res['signal'] in signals_summary:
                signals_summary[res['signal']].append(res['code'])

    send_email(signals_summary)
    print("Processing completed.")

if __name__ == "__main__":
    main()
