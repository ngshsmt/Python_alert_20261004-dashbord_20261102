# Pythonメインスクリプト（screener.py）

import datetime
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
import requests
import pandas as pd
import pandas_ta as ta
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
# 2. テクニカル指標計算 & シグナル判定関数
# ==========================================
def analyze_ticker(ticker_symbol):
    """
    指定された銘柄のデータを取得し、Supertrend + Simple MAのシグナルを判定する
    """
    try:
        # 直近100日分のデータ取得（SMA50やSupertrend計算に十分な期間）
        df = yf.download(ticker_symbol, period="100d", interval="1d", progress=False)
        if df.empty or len(df) < 50:
            return None

        # yfinanceのMultiIndexカラム対策
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df['Close']
        high = df['High']
        low = df['Low']

        # 移動平均線
        df['SMA5'] = ta.sma(close, length=5)
        df['SMA10'] = ta.sma(close, length=10)
        df['SMA20'] = ta.sma(close, length=20)
        df['SMA50'] = ta.sma(close, length=50)

        # Supertrend (Period=10, Factor=3.0)
        st_df = ta.supertrend(high, low, close, length=10, multiplier=3.0)
        # st_dfのカラム例: SUPERT_10_3.0, SUPERTd_10_3.0 (1=Buy, -1=Sell)
        st_dir_col = [col for col in st_df.columns if col.startswith("SUPERTd")][0]
        st_val_col = [col for col in st_df.columns if col.startswith("SUPERT_") and not col.startswith("SUPERTd")][0]

        df['ST_Direction'] = st_df[st_dir_col] # 1: Buy(isStBuy), -1: Sell
        df['ST_Value'] = st_df[st_val_col]     # 下限バンド（損切り価格目安）

        # パーフェクトオーダー条件
        df['isSimplePO'] = (df['SMA5'] > df['SMA10']) & (df['SMA10'] > df['SMA20']) & (close > df['SMA50'])
        df['isStBuy'] = df['ST_Direction'] == 1

        # 条件判定用（前日との変化）
        df['st_change'] = df['ST_Direction'].diff()
        df['sma_cross'] = (df['SMA5'] > df['SMA10']) & (df['SMA5'].shift(1) <= df['SMA10'].shift(1))

        # 買いエントリー条件
        df['longEntryCond'] = df['isStBuy'] & df['isSimplePO'] & ((df['st_change'] > 0) | df['sma_cross'])
        # 買い手仕舞い条件
        df['longExitCond'] = (df['SMA5'] < df['SMA20']) | (~df['isStBuy'])

        # 直近（大引け時点）の行を取得
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 状態判定（簡易版）
        # ※本来は全期間ループで正確なシグナル転換を追うが、当日発生シグナルを判定
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
# 3. Notion DB登録関数
# ==========================================
def push_to_notion(result_data, company_name=""):
    """
    Notion APIを使ってデータベースへレコードを追加する
    """
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
            "ステータス": {"status": {"name": "未対応"}}
        }
    }

    res = requests.post(url, headers=headers, json=payload)
    if res.status_code != 200:
        print(f"Failed to push to Notion: {res.text}")

# ==========================================
# 4. メール送信関数
# ==========================================
def send_email(signals_dict):
    """
    指定のフォーマットでメールを送信する
    """
    if not SMTP_USER or not SMTP_PASS or not MAIL_TO:
        print("SMTP credentials not provided. Skipping email dispatch.")
        return

    # 曜日変換
    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    date_str = now_jst.strftime("%Y/%m/%d")
    weekday_str = weekdays_jp[now_jst.weekday()]

    subject = f"{date_str}({weekday_str})の対象銘柄コード"

    # リスト文字列作成
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
# 5. メイン実行フロー
# ==========================================
def main():
    # 1. watchlist.csv 読み込み
    csv_path = "watchlist.csv"
    if not os.path.exists(csv_path):
        print(f"{csv_path} not found.")
        return

    df_watchlist = pd.read_csv(csv_path)
    # カラム名が 'code' または 'ticker' に対応
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
        # 日本株用に '.T' 付与（すでに付いている場合はそのまま）
        ticker = code if code.endswith(".T") else f"{code}.T"
        res = analyze_ticker(ticker)

        if res and res['signal']:
            print(f"Signal detected: {res['code']} -> {res['signal']}")
            # Notionへ登録
            push_to_notion(res)
            # メール通知用サマリーに追加
            if res['signal'] in signals_summary:
                signals_summary[res['signal']].append(res['code'])

    # 2. メール送信
    send_email(signals_summary)
    print("Processing completed.")

if __name__ == "__main__":
    main()
