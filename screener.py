# Pythonメインスクリプト（screener.py）_1.0.1

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
# 2. Supertrend自作計算ロジック (10, 3.0)
# ==========================================
def calculate_supertrend(df, period=10, multiplier=3.0):
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # True Range & ATR の計算
    price_diff1 = high - low
    price_diff2 = (high - close.shift(1)).abs()
    price_diff3 = (low - close.shift(1)).abs()
    true_range = pd.concat([price_diff1, price_diff2, price_diff3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1/period, adjust=False).mean()

    # Upper / Lower Band の計算
    hl2 = (high + low) / 2
    basic_ub = hl2 + (multiplier * atr)
    basic_lb = hl2 - (multiplier * atr)

    final_ub = np.zeros(len(df))
    final_lb = np.zeros(len(df))
    st_dir = np.zeros(len(df))

    for i in range(1, len(df)):
        # Final Upper Band
        if basic_ub.iloc[i] < final_ub[i-1] or close.iloc[i-1] > final_ub[i-1]:
            final_ub[i] = basic_ub.iloc[i]
        else:
            final_ub[i] = final_ub[i-1]

        # Final Lower Band
        if basic_lb.iloc[i] > final_lb[i-1] or close.iloc[i-1] < final_lb[i-1]:
            final_lb[i] = basic_lb.iloc[i]
        else:
            final_lb[i] = final_lb[i-1]

        # Direction (1: Buy, -1: Sell)
        if st_dir[i-1] == 1:
            if close.iloc[i] < final_lb[i]:
                st_dir[i] = -1
            else:
                st_dir[i] = 1
        else:
            if close.iloc[i] > final_ub[i]:
                st_dir[i] = 1
            else:
                st_dir[i] = -1

    st_val = np.where(st_dir == 1, final_lb, final_ub)
    return pd.Series(st_dir, index=df.index), pd.Series(st_val, index=df.index)

# ==========================================
# 3. テクニカル指標計算 & シグナル判定関数
# ==========================================
def analyze_ticker(ticker_symbol):
    try:
        df = yf.download(ticker_symbol, period="100d", interval="1d", progress=False)
        if df.empty or len(df) < 50:
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

        # パーフェクトオーダー条件
        df['isSimplePO'] = (df['SMA5'] > df['SMA10']) & (df['SMA10'] > df['SMA20']) & (close > df['SMA50'])
        df['isStBuy'] = df['ST_Direction'] == 1

        # 条件判定用
        df['st_change'] = df['ST_Direction'].diff()
        df['sma_cross'] = (df['SMA5'] > df['SMA10']) & (df['SMA5'].shift(1) <= df['SMA10'].shift(1))

        # 買いエントリー条件
        df['longEntryCond'] = df['isStBuy'] & df['isSimplePO'] & ((df['st_change'] > 0) | df['sma_cross'])
        # 買い手仕舞い条件
        df['longExitCond'] = (df['SMA5'] < df['SMA20']) | (~df['isStBuy'])

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        signal = None
        if latest['longEntryCond']:
            signal = "Long"
        elif latest['longExitCond'] and prev['isStBuy']:
            signal = "Exit L"

        return {
            "symbol": ticker_symbol,
            "code": ticker_symbol.replace(".T", ""),
            "close": float(latest['Close']),
            "st_val": float(latest['ST_Value']),
            "signal": signal
        }
    except Exception as e:
        print(f"Error processing {ticker_symbol}: {e}")
        return None

# ==========================================
# 4. Notion DB登録関数
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
            "ステータス": {"select": {"name": "未対応"}}
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    if res.status_code != 200:
        print(f"Failed to push to Notion: {res.text}")

# ==========================================
# 5. メール送信関数
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
# 6. メイン実行フロー
# ==========================================
def main():
    csv_path = "watchlist.csv"
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
