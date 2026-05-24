"""
meti_morning_alert.py
毎朝8:30に実行。
公表予定XMLを確認して、今日が公表日であればDiscordに通知する。
"""
import os
import requests
import xml.etree.ElementTree as ET
from datetime import date

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
XML_URL = "https://www.meti.go.jp/statistics/tyo/seidou/yotei/xml/e-stat_seidou.xml"
RESULT_PAGE_URL = "https://www.meti.go.jp/statistics/tyo/seidou/result/ichiran/08_seidou.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UpdateChecker/1.0)"}


def check_publication_day():
    today = date.today().isoformat()
    try:
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
                    "time": time_val or "時刻未定",
                    "type": type_val or "公表",
                    "month": month_val,
                })
        return results
    except Exception as e:
        print(f"XML取得エラー: {e}")
        return []


def send_discord(events):
    today = date.today().isoformat()
    embeds = []
    for e in events:
        month_str = f"（{e['month']}）" if e["month"] else ""
        embeds.append({
            "title": f"📋 本日は経済産業省生産動態統計調査 {e['type']}版{month_str}の公表日です",
            "description": (
                f"🕐 **{e['time']} 公表予定**\n\n"
                f"経産省サイトからExcelをダウンロードして、\n"
                f"Claudeにファイルを渡してください。\n\n"
                f"🔗 [公表ページ]({RESULT_PAGE_URL}#menu1)"
            ),
            "color": 0x003087,
            "footer": {"text": f"📅 {today}  |  経済産業省生産動態統計調査"},
        })
    r = requests.post(DISCORD_WEBHOOK, json={"embeds": embeds}, timeout=10)
    r.raise_for_status()
    print(f"Discord通知を送信しました（{len(embeds)}件）")


def main():
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        exit(1)

    today = date.today().isoformat()
    print(f"実行日: {today}")

    events = check_publication_day()
    if events:
        print(f"本日は公表日です: {[e['type'] for e in events]}")
        send_discord(events)
    else:
        print("本日は公表日ではありません")


if __name__ == "__main__":
    main()
