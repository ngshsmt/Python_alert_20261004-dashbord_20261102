# tracker.py_v1.0.0

import os
import datetime
import pandas as pd
import yfinance as yf
from gspread import service_account

# ==========================================
# 1. 環境変数・設定値
# ==========================================
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "シート1(GAS連携中)")
SERVICE_ACCOUNT_FILE = os.environ.get("SERVICE_ACCOUNT_FILE", "service_account.json")

# ==========================================
# 2. 補助関数：初寄り日の特定
# ==========================================
def find_first_trade_day(ticker_symbol, signal_date_str):
    """
    点灯日付の翌営業日以降、初めて Volume > 0（売買成立）となった営業日と始値(Open)を特定する
    """
    try:
        # yfinance用シンボル調整（日本株 4桁コード対応）
        ticker = ticker_symbol if ticker_symbol.endswith(".T") else f"{ticker_symbol}.T"
        
        # 点灯日付の翌日から本日までの株価データを取得
        signal_date = pd.to_datetime(signal_date_str)
        start_date = signal_date + pd.Timedelta(days=1)
        today = datetime.date.today() + datetime.timedelta(days=1)
        
        df = yf.download(ticker, start=start_date.strftime("%Y-%m-%d"), end=today.strftime("%Y-%m-%d"), progress=False)
        if df.empty:
            return None, None

        # yfinanceのMultiIndex対策
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 出来高 Volume > 0 かつ 始値 Open が存在する最初の行を探す
        traded_df = df[(df['Volume'] > 0) & (df['Open'].notnull())]
        if traded_df.empty:
            return None, None  # まだ寄り付いていない（寄らずストップ高/安が継続中）

        # 最初に寄り付いた営業日の日付と始値
        first_row = traded_df.iloc[0]
        first_date_dt = traded_df.index[0]
        
        # 「YYYY/MM/DD」形式（スラッシュ区切り）にフォーマット
        first_date_str = first_date_dt.strftime("%Y/%m/%d")
        open_price = float(first_row['Open'])
        
        return first_date_str, open_price

    except Exception as e:
        print(f"Error checking market data for {ticker_symbol}: {e}")
        return None, None

# ==========================================
# 3. メイン処理：スプレッドシートの追跡・更新
# ==========================================
def run_tracker():
    if not SPREADSHEET_ID:
        print("エラー: SPREADSHEET_ID が設定されていません。")
        return

    # Google Sheets API 認証とシート取得
    try:
        gc = service_account(filename=SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet(SHEET_NAME)
    except Exception as e:
        print(f"Google Sheets 接続エラー: {e}")
        return

    # 全データ（A列〜S列）を取得
    records = worksheet.get_all_values()
    if len(records) <= 1:
        print("スプレッドシートにデータ行がありません。")
        return

    header = records[0]
    data_rows = records[1:]
    
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] スキャン開始 (対象行数: {len(data_rows)})")

    # 1行ずつ追跡対象（未確定セル）があるか判定
    for idx, row in enumerate(data_rows):
        row_num = idx + 2  # ヘッダーが1行目のため、実際のシート行番号は idx + 2
        
        # 19列未満の空行はスキップ
        if len(row) < 19:
            row += [""] * (19 - len(row))

        # カラムマッピング (0始まりインデックス)
        # B(1): エントリー点灯日付, C(2): エントリー日付, D(3): 消灯日付, E(4): 手仕舞い日付
        # F(5): 銘柄コード, L(11): 想定エントリー価格, M(12): エントリー価格, P(15): 手仕舞い価格
        entry_signal_date = row[1].strip()
        entry_date = row[2].strip()
        exit_signal_date = row[3].strip()
        exit_date = row[4].strip()
        code = row[5].strip()
        entry_price = row[12].strip()
        exit_price = row[15].strip()

        if not code:
            continue

        # ----------------------------------------------------
        # A. エントリー追跡：点灯日(B列)があり、エントリー日付(C列)または価格(M列)が空欄
        # ----------------------------------------------------
        if entry_signal_date and (not entry_date or not entry_price):
            print(f"行 {row_num} ({code}): エントリー寄り付き確認中 (点灯日: {entry_signal_date})...")
            trade_date, open_price = find_first_trade_day(code, entry_signal_date)
            
            if trade_date and open_price:
                # C列（エントリー日付）と M列（エントリー価格）をピンポイント更新
                worksheet.update_acell(f"C{row_num}", trade_date)
                worksheet.update_acell(f"M{row_num}", open_price)
                print(f" -> 【エントリー確定】 行 {row_num} ({code}): C列={trade_date}, M列={open_price}")

        # ----------------------------------------------------
        # B. 手仕舞い追跡：消灯日(D列)があり、手仕舞い日付(E列)または価格(P列)が空欄
        # ----------------------------------------------------
        if exit_signal_date and (not exit_date or not exit_price):
            print(f"行 {row_num} ({code}): 手仕舞い寄り付き確認中 (消灯日: {exit_signal_date})...")
            trade_date, open_price = find_first_trade_day(code, exit_signal_date)
            
            if trade_date and open_price:
                # E列（手仕舞い日付）と P列（手仕舞い価格）をピンポイント更新
                worksheet.update_acell(f"E{row_num}", trade_date)
                worksheet.update_acell(f"P{row_num}", open_price)
                print(f" -> 【手仕舞い確定】 行 {row_num} ({code}): E列={trade_date}, P列={open_price}")

    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] トラッキング処理完了。")

if __name__ == "__main__":
    run_tracker()
