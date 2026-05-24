"""
meti_notify.py
経済産業省生産動態統計調査の公表当日に実行：
1. 公表予定XMLで当日が公表日か確認
2. 経産省サイトから当年速報版Excelをダウンロード
3. リポジトリ内の前年確報版Excelで前年同月比を計算
4. 指定品目の全項目と変化率（前月比・前年同月比）をDiscordに通知
5. 前月比2か月連続20%増の品目をアラート通知
"""
import os
import io
import re
import requests
import pandas as pd
import numpy as np
from datetime import date
from bs4 import BeautifulSoup

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
XML_URL = "https://www.meti.go.jp/statistics/tyo/seidou/yotei/xml/e-stat_seidou.xml"
RESULT_PAGE_URL = "https://www.meti.go.jp/statistics/tyo/seidou/result/ichiran/08_seidou.html"
METI_TOP_URL = "https://www.meti.go.jp"

# リポジトリ内の前年確報版ファイル
PREV_YEAR_FILE = "h2daa2025_hosei_jikei.xlsx"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UpdateChecker/1.0)"}

TARGET_ITEMS = [
    "リジッド系モジュール基板",
    "アルミ電解コンデンサ",
    "標準油入り変圧器（電力会社向け）",
    "標準油入り変圧器（電力会社向け以外）",
]

ALERT_THRESHOLD = 20.0

COL_ITEM = 5
COL_ATTR = 6
COL_UNIT = 7
MONTH_START = 8
MONTH_END = 20


# ── 1. 公表日チェック ───────────────────────────────────

def is_publication_day():
    today = date.today().isoformat()
    try:
        import xml.etree.ElementTree as ET
        r = requests.get(XML_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        results = []
        for record in root:
            all_text = " ".join((e.text or "") for e in record.iter() if e.text)
            if today in all_text or today.replace("-", "/") in all_text:
                time_val, type_val, month_val = "", "", ""
                for e in record.iter():
                    t = (e.text or "").strip()
                    if len(t) == 5 and t[2] == ":" and t[:2].isdigit():
                        time_val = t
                    if "速報" in t and not type_val:
                        type_val = "速報"
                    elif "確報" in t and not type_val:
                        type_val = "確報"
                    if ("月分" in t or "月期" in t) and not month_val:
                        month_val = t
                results.append({
                    "date": today,
                    "time": time_val or "時刻未定",
                    "type": type_val or "公表",
                    "month": month_val,
                })
        return results
    except Exception as e:
        print(f"XML取得エラー: {e}")
        return []


# ── 2. 当年速報版Excelをダウンロード ────────────────────

def find_sokuho_url():
    r = requests.get(RESULT_PAGE_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r'\d{6}s\.xlsx$', href, re.IGNORECASE):
            url = href if href.startswith("http") else METI_TOP_URL + href
            print(f"  速報版発見: {url}")
            return url
    return None


def download_excel(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_excel(io.BytesIO(r.content), sheet_name="実数表", header=None)


def load_prev_year_excel():
    if not os.path.exists(PREV_YEAR_FILE):
        print(f"WARNING: 前年ファイル {PREV_YEAR_FILE} が見つかりません")
        return None
    print(f"  前年確報版を読み込み: {PREV_YEAR_FILE}")
    return pd.read_excel(PREV_YEAR_FILE, sheet_name="実数表", header=None)


# ── 3. データ解析 ───────────────────────────────────────

def get_month_cols(df):
    month_cols = {}
    for col_idx in range(MONTH_START, MONTH_END):
        val = df.iloc[1, col_idx]
        if pd.notna(val):
            month_cols[str(int(float(val)))] = col_idx
    return month_cols


def safe_float(v):
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except:
        return None


def calc_rate(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100


def format_rate(rate):
    if rate is None:
        return "計算不可"
    sign = "+" if rate >= 0 else ""
    return f"{sign}{rate:.1f}%"


def month_label(m):
    return f"{m[:4]}年{int(m[4:6])}月"


def fmt_val(val, unit):
    if val is None:
        return "非公表"
    if val >= 1_000_000:
        return f"{val/1_000_000:.2f}百万 {unit}"
    if val >= 10_000:
        return f"{val:,.0f} {unit}"
    return f"{val:,.1f} {unit}"


def build_prev_year_dict(df_prev):
    """前年確報版から {(品目名, アイテム名, 月): 値} の辞書を作成"""
    month_cols = get_month_cols(df_prev)
    data = df_prev.iloc[2:].copy()
    data.columns = range(len(data.columns))
    d = {}
    for _, row in data.iterrows():
        item = str(row[COL_ITEM])
        attr = str(row[COL_ATTR])
        for month, col in month_cols.items():
            d[(item, attr, month)] = safe_float(row[col])
    return d


def analyze_target_items(df_curr, prev_year_dict=None):
    month_cols_curr = get_month_cols(df_curr)
    sorted_months = sorted(month_cols_curr.keys())
    latest_month = sorted_months[-1] if sorted_months else None
    prev_month = sorted_months[-2] if len(sorted_months) >= 2 else None

    data_curr = df_curr.iloc[2:].copy()
    data_curr.columns = range(len(data_curr.columns))

    results = []
    for target in TARGET_ITEMS:
        rows = data_curr[data_curr[COL_ITEM].astype(str).str.contains(target, na=False)]
        if rows.empty:
            continue

        item_result = {"name": target, "attrs": []}
        for _, row in rows.iterrows():
            attr = str(row[COL_ATTR])
            unit = str(row[COL_UNIT])
            curr_val = safe_float(row[month_cols_curr.get(latest_month)]) if latest_month else None
            prev_val = safe_float(row[month_cols_curr.get(prev_month)]) if prev_month else None

            # 前年同月比：前年の同じ月のデータを参照
            prev_year_val = None
            if prev_year_dict and latest_month:
                prev_year_month = str(int(latest_month[:4]) - 1) + latest_month[4:]
                prev_year_val = prev_year_dict.get((str(row[COL_ITEM]), attr, prev_year_month))

            item_result["attrs"].append({
                "attr": attr,
                "unit": unit,
                "curr_val": curr_val,
                "mom_rate": calc_rate(curr_val, prev_val),
                "yoy_rate": calc_rate(curr_val, prev_year_val),
            })
        results.append(item_result)
    return results, latest_month, prev_month


def find_alert_items(df_curr):
    """前月比2か月連続ALERT_THRESHOLD%以上増の品目を検出（指定品目除く）"""
    month_cols = get_month_cols(df_curr)
    sorted_months = sorted(month_cols.keys())
    if len(sorted_months) < 3:
        return []

    m3, m2, m1 = sorted_months[-1], sorted_months[-2], sorted_months[-3]
    data = df_curr.iloc[2:].copy()
    data.columns = range(len(data.columns))

    alerts = []
    for _, row in data.iterrows():
        item = str(row[COL_ITEM])
        if any(t in item for t in TARGET_ITEMS):
            continue
        attr = str(row[COL_ATTR])
        unit = str(row[COL_UNIT])
        v1 = safe_float(row[month_cols[m1]])
        v2 = safe_float(row[month_cols[m2]])
        v3 = safe_float(row[month_cols[m3]])
        r2 = calc_rate(v2, v1)
        r3 = calc_rate(v3, v2)
        if r2 is not None and r3 is not None and r2 >= ALERT_THRESHOLD and r3 >= ALERT_THRESHOLD:
            alerts.append({
                "item": item, "attr": attr, "unit": unit,
                "month2": m2, "month3": m3, "r2": r2, "r3": r3,
            })
    return alerts[:10]


# ── 4. Discord送信 ──────────────────────────────────────

def send_discord_report(pub_info, target_results, latest_month, prev_month, alerts):
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が未設定")
        return

    embeds = []

    # ① 公表通知
    for p in pub_info:
        month_str = f"（{p['month']}）" if p["month"] else ""
        embeds.append({
            "title": f"📊 経済産業省生産動態統計調査 {p['type']}版{month_str} 公表日",
            "description": (
                f"🕐 {p['time']} 公表\n"
                f"🔗 [公表結果はこちら]({RESULT_PAGE_URL}#menu1)"
            ),
            "color": 0x003087,
            "footer": {"text": f"📅 {p['date']}"},
        })

    # ② 指定品目レポート
    if target_results and latest_month:
        latest_m_label = month_label(latest_month)
        for item_res in target_results:
            lines = [f"**{latest_m_label}実績** （前月比 ／ 前年同月比）\n"]
            for a in item_res["attrs"]:
                curr_str = fmt_val(a["curr_val"], a["unit"])
                mom_str = format_rate(a["mom_rate"])
                yoy_str = format_rate(a["yoy_rate"])
                mom_rate = a["mom_rate"] or 0
                icon = "🔺" if mom_rate > 0 else "🔻" if mom_rate < 0 else "➡️"
                lines.append(
                    f"**{a['attr']}**\n"
                    f"　{curr_str}\n"
                    f"　{icon} 前月比: **{mom_str}**　｜　前年同月比: **{yoy_str}**"
                )
            embeds.append({
                "title": f"📋 {item_res['name']}",
                "description": "\n".join(lines),
                "color": 0x00aaff,
            })

    # ③ 2か月連続増加アラート
    if alerts:
        alert_lines = []
        for a in alerts:
            alert_lines.append(
                f"**{a['item']}** {a['attr']}（{a['unit']}）\n"
                f"　{month_label(a['month2'])}: {format_rate(a['r2'])}　→　"
                f"{month_label(a['month3'])}: {format_rate(a['r3'])}"
            )
        embeds.append({
            "title": f"🚨 前月比2か月連続{ALERT_THRESHOLD:.0f}%以上増の品目",
            "description": "\n".join(alert_lines),
            "color": 0xff4400,
        })
    else:
        embeds.append({
            "title": f"✅ 前月比2か月連続{ALERT_THRESHOLD:.0f}%以上増",
            "description": "該当品目はありませんでした",
            "color": 0x888888,
        })

    for i in range(0, len(embeds), 10):
        r = requests.post(DISCORD_WEBHOOK, json={"embeds": embeds[i:i+10]}, timeout=10)
        r.raise_for_status()

    print(f"Discord通知送信完了（embed {len(embeds)}件）")


# ── メイン ──────────────────────────────────────────────

def main():
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        exit(1)

    today = date.today().isoformat()
    print(f"実行日: {today}")

    # テストモード：環境変数 METI_TEST=1 で公表日チェックをスキップ
    test_mode = os.environ.get("METI_TEST") == "1"

    if test_mode:
        print("⚠️ テストモードで実行中（公表日チェックをスキップ）")
        pub_info = [{"date": today, "time": "13:30（テスト）", "type": "速報", "month": "テスト月分"}]
    else:
        pub_info = is_publication_day()
        if not pub_info:
            print("本日は公表日ではありません")
            return

    print(f"公表日を確認: {[p['type'] for p in pub_info]}")

    # 当年速報版をダウンロード
    print("当年速報版Excelを探しています...")
    sokuho_url = find_sokuho_url()
    if not sokuho_url:
        print("WARNING: 速報版Excelが見つかりませんでした。公表通知のみ送信します")
        send_discord_report(pub_info, [], None, None, [])
        return

    print("速報版をダウンロード中...")
    df_curr = download_excel(sokuho_url)

    # 前年確報版をリポジトリから読み込み
    print("前年確報版を読み込み中...")
    df_prev = load_prev_year_excel()
    prev_year_dict = build_prev_year_dict(df_prev) if df_prev is not None else None

    # 分析
    print("指定品目を分析中...")
    target_results, latest_month, prev_month = analyze_target_items(df_curr, prev_year_dict)

    print("連続増加アラートを検出中...")
    alerts = find_alert_items(df_curr)
    print(f"  アラート該当: {len(alerts)}件")

    send_discord_report(pub_info, target_results, latest_month, prev_month, alerts)


if __name__ == "__main__":
    main()
