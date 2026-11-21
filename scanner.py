import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta

BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

DB_FILE = "DSE_Master_Database.csv"
SIGNAL_LOG_FILE = "DSE_Signal_History.csv"
HOLDING_FILE = "DSE_Holdings_Log.csv"

headers = {'User-Agent': 'Mozilla/5.0'}

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print(msg)
        return
    url = f"https://telegram.org{BOT_TOKEN}/sendMessage"
    for i in range(0, len(msg), 4000):
        requests.post(url, data={'chat_id': CHAT_ID, 'text': msg[i:i+4000], 'parse_mode': 'Markdown'})

def fetch_dse_eod():
    url = "https://dsebd.org"
    try:
        res = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.find('table', {'class': 'shares-table'})
        if not table:
            return pd.DataFrame()
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        rows = []
        for tr in table.find_all('tr')[1:]:
            cols = [c.text.strip().replace(',', '') for c in tr.find_all('td')]
            if len(cols) >= 11:
                try:
                    sym = cols
                    ltp = float(cols) if cols != '--' else 0.0
                    high = float(cols) if cols != '--' else 0.0
                    low = float(cols) if cols != '--' else 0.0
                    closep = float(cols) if cols != '--' else 0.0
                    ycp = float(cols) if cols != '--' else 0.0
                    trade = int(cols) if cols != '--' else 0
                    value_mn = float(cols) if cols != '--' else 0.0
                    volume = int(cols) if cols != '--' else 0
                    
                    if volume > 0 and closep > 0:
                        rows.append({
                            'Date': today_str, 'Symbol': sym, 'LTP': ltp, 'High': high,
                            'Low': low, 'Close': closep, 'YCP': ycp, 'Trade': trade,
                            'Value_Mn': value_mn, 'Volume': volume
                        })
                except:
                    continue
        return pd.DataFrame(rows)
    except Exception as e:
        return pd.DataFrame()

def fetch_block_market():
    url = "https://dsebd.org"
    block_dict = {}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        for table in soup.find_all('table'):
            if "Instr Code" in table.text:
                for tr in table.find_all('tr')[1:]:
                    cols = [c.text.strip().replace(',', '') for c in tr.find_all('td')]
                    if len(cols) >= 6:
                        try:
                            block_dict[cols] = {
                                'Max': float(cols), 'Min': float(cols),
                                'Trades': int(cols), 'Qty': int(cols), 'Val_Mn': float(cols)
                            }
                        except:
                            continue
    except:
        pass
    return block_dict

def check_company_intel(symbol, old_holdings_df):
    url = f"https://dsebd.org{symbol}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        text = res.text
        alerts = []
        if "Sale Declaration" in text or "intention to sell" in text.lower():
            alerts.append("⚠️ Director Sell")
        if "Record Date" in text:
            alerts.append("📅 Record Date")
            
        inst = re.findall(r'Institute\s*:\s*([\d.]+)', text)
        foreign = re.findall(r'Foreign\s*:\s*([\d.]+)', text)
        curr_inst = float(inst[-1]) if inst else 0.0
        curr_for = float(foreign[-1]) if foreign else 0.0
        
        holding_msg = f"Inst:{curr_inst}%"
        if not old_holdings_df.empty and symbol in old_holdings_df['Symbol'].values:
            prev_inst = old_holdings_df.loc[old_holdings_df['Symbol'] == symbol, 'Inst'].values[-1]
            if curr_inst > prev_inst:
                holding_msg += f" (⬆️+{round(curr_inst-prev_inst, 2)}%)"
                
        return curr_inst, curr_for, holding_msg, ", ".join(alerts) if alerts else "Clear"
    except:
        return 0.0, 0.0, "N/A", "Check"

def analyze_stock(hist_df, today_row, block_info):
    df = hist_df.sort_values('Date').tail(25).copy()
    days_count = len(df)
    
    ltp = today_row['LTP']
    high = today_row['High']
    low = today_row['Low']
    close = today_row['Close']
    ycp = today_row['YCP']
    vol = today_row['Volume']
    val_mn = today_row['Value_Mn']
    trade = today_row['Trade']
    
    close_gt_ltp = (close > ltp) and (val_mn >= 0.5)
    vwap = (val_mn * 1000000) / vol if vol > 0 else close
    close_gt_vwap = close >= vwap
    avg_trade_val = (val_mn * 1000000) / trade if trade > 0 else 0
    big_hand_trade = avg_trade_val >= 80000
    
    day_swing = ((high - low) / low * 100) if low > 0 else 0
    close_pos = ((close - low) / (high - low)) if (high - low) > 0 else 0.5
    wyckoff_spring = (day_swing >= 3.5) and (close_pos >= 0.70)
    
    signals = []
    score = 0
    
    if close_gt_ltp:
        signals.append("Close>LTP")
        score += 2
    if close_gt_vwap and big_hand_trade:
        signals.append(f"BigHand(৳{int(avg_trade_val/1000)}k/trd)")
        score += 1
    if wyckoff_spring:
        signals.append("⚡Wyckoff Spring")
        score += 2
        
    exit_alert = False
    if days_count >= 5:
        avg_val = df['Value_Mn'].iloc[:-1].mean()
        val_ratio = val_mn / avg_val if avg_val > 0 else 1.0
        
        max_p = df['High'].max()
        min_p = df['Low'].min()
        box_range = ((max_p - min_p) / min_p * 100) if min_p > 0 else 0
        
        mfm = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / (df['High'] - df['Low']).replace(0, np.nan)
        mfv = mfm.fillna(0) * df['Volume']
        cmf = mfv.sum() / df['Volume'].sum() if df['Volume'].sum() > 0 else 0
        
        obv = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
        obv_rising = obv.iloc[-1] > obv.iloc
        
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).mean()
        loss = -delta.clip(upper=0).mean()
        rs = gain / loss if loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        if val_ratio >= 1.8:
            signals.append(f"Vol/Val {round(val_ratio,1)}x")
            score += 2
        if box_range <= 12.0 and obv_rising:
            signals.append("Box+OBV↑")
            score += 2
        if cmf >= 0.05:
            signals.append(f"CMF({round(cmf,2)})")
            score += 1
        if 40 <= rsi <= 58 and obv_rising:
            signals.append(f"RSI({int(rsi)})")
            score += 1
            
        if rsi >= 75 and close_pos <= 0.35 and val_ratio >= 2.5:
            exit_alert = True

    if block_info:
        if block_info['Max'] >= close:
            signals.append(f"🔥Block({block_info['Val_Mn']}M)")
            score += 2
        else:
            signals.append(f"DiscBlock({block_info['Val_Mn']}M)")
            score -= 1
            
    return score, signals, exit_alert

def main():
    today_df = fetch_dse_eod()
    
    if today_df.empty or len(today_df) < 200 or today_df['Value_Mn'].sum() < 10:
        print("আজ মার্কেট বন্ধ বা ডেটা অসম্পূর্ণ।")
        return

    today_str = today_df['Date'].iloc
    
    if os.path.exists(DB_FILE):
        master_df = pd.read_csv(DB_FILE)
        master_df = master_df[master_df['Date'] != today_str]
        master_df = pd.concat([master_df, today_df], ignore_index=True)
    else:
        master_df = today_df.copy()
        
    master_df.to_csv(DB_FILE, index=False)
    
    block_data = fetch_block_market()
    old_holdings = pd.read_csv(HOLDING_FILE) if os.path.exists(HOLDING_FILE) else pd.DataFrame()
    
    buy_list = []
    watch_list = []
    exit_list = []
    new_holdings = []
    
    for _, row in today_df.iterrows():
        sym = row['Symbol']
        if row['Value_Mn'] < 0.5 and sym not in block_data:
            continue
            
        hist_df = master_df[master_df['Symbol'] == sym]
        score, sigs, is_exit = analyze_stock(hist_df, row, block_data.get(sym))
        
        if is_exit:
            exit_list.append(f"• *{sym}* (৳{row['Close']}) - চূড়ায় ক্লাইম্যাক্স/রিভার্সাল!")
            
        if score >= 3:
            inst, for_h, h_msg, alert_msg = check_company_intel(sym, old_holdings)
            new_holdings.append({'Date': today_str, 'Symbol': sym, 'Inst': inst, 'Foreign': for_h})
            
            if "Director Sell" in alert_msg:
                continue
                
            entry_text = f"• *{sym}* | ৳{row['Close']} | টার্নওভার: {row['Value_Mn']}M\n  └ সূত্র: {', '.join(sigs)} | {h_msg} | {alert_msg}"
            if score >= 5:
                buy_list.append((sym, entry_text))
            else:
                watch_list.append((sym, entry_text))

    if os.path.exists(SIGNAL_LOG_FILE):
        sig_df = pd.read_csv(SIGNAL_LOG_FILE)
    else:
        sig_df = pd.DataFrame(columns=['Date', 'Symbol', 'Close', 'Type'])
        
    cutoff_date = (datetime.now() - timedelta(days=18)).strftime('%Y-%m-%d')
    recent_sigs = sig_df[sig_df['Date'] >= cutoff_date]
    
    final_buy_msgs = []
    for sym, text in buy_list:
        rep = len(recent_sigs[recent_sigs['Symbol'] == sym]) + 1
        final_buy_msgs.append(f"{text}\n  └ 🔁 গত ২ সপ্তাহে *{rep} বার* সিগন্যাল")
        sig_df = pd.concat([sig_df, pd.DataFrame([{'Date': today_str, 'Symbol': sym, 'Close': today_df.loc[today_df['Symbol']==sym, 'Close'].values, 'Type': 'BUY'}])], ignore_index=True)

    sig_df.drop_duplicates(subset=['Date', 'Symbol'], keep='last').to_csv(SIGNAL_LOG_FILE, index=False)
    
    if new_holdings:
pd.concat([old_holdings, pd.DataFrame(new_holdings)]).drop_duplicates(subset=['Symbol'], keep='last').to_csv(HOLDING_FILE, index=False)
report = f"📊 DSE স্মার্ট একুমুলেশন স্ক্যানার ({today_str})\n"
report += f"মোট সংরক্ষিত ডেটা দিন: {master_df['Date'].nunique()} কার্যদিবস\n"
report += "="*30 + "\n\n"
if final_buy_msgs:
report += "🚀 STRONG ACCUMULATION / PRE-BREAKOUT:\n" + "\n\n".join(final_buy_msgs[:10]) + "\n\n"
else:
report += "🚀 STRONG ACCUMULATION: আজ শক্তিশালী কোনো ব্রেকআউট মেলেনি।\n\n"
if watch_list:
report += "👀 EARLY WATCHLIST (সংগ্রহ চলছে):\n" + "\n".join([x for x in watch_list[:8]]) + "\n\n"
if exit_list:
report += "🚨 EXIT / PROFIT BOOKING ALERT:\n" + "\n".join(exit_list[:5]) + "\n"
send_telegram(report)
if name == "main":
main() 
