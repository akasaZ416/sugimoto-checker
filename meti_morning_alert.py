"""
meti_morning_alert.py
毎朝8:30に実行。
公表予定XMLを確認して、今日が公表日であればDiscordに通知する。
"""
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# METI の公表日は JST の暦日。GitHub Actions ランナーは UTC で動くため、
# date.today()(=UTC) を使うと公表前夜(JST朝=UTC前日)に「前日」と判定されマッチしない。
# 従来は GitHub のスケジュール遅延で UTC 日付がたまたま繰り上がって動いていただけなので、
# 必ず JST で today を取って堅牢化する。
JST = timezone(timedelta(hours=9))


def _today_jst():
    return datetime.now(JST).date()


DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
XML_URL = "https://www.meti.go.jp/statistics/tyo/seidou/yotei/xml/e-stat_seidou.xml"
RESULT_PAGE_URL = "https://www.meti.go.jp/statistics/tyo/seidou/result/ichiran/08_seidou.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UpdateChecker/1.0)"}


def check_publication_day():
    """METI 公表予定 XML を取得し、今日(JST)が公表日のレコードを返す。

    XML の実構造（os_code Ver.2.163）:
      <e-stat><os_code name="...">
        <class_1 name="2026年"><class_2 name="4月分"><class_3 name="速報">
          <class_4 name=""><class_5 name="">
            <release_year>2026</release_year><release_month>5</release_month>
            <release_day>29</release_day>
            <release_hour>8</release_hour><release_minute>50</release_minute>
      → 日付は要素分割、種別(速報/確報)と月分(4月分)は class_N の name 属性に入る。
        以前の「ISO 日付文字列を含むか」判定では永久にマッチしなかったため要素ベースに変更。
      エンコーディングは UTF-16 宣言。requests の自動判定に頼らず明示デコードする。
    """
    today = _today_jst()
    try:
        r = requests.get(XML_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        try:
            text = r.content.decode("utf-16")
        except UnicodeError:
            text = r.text
        root = ET.fromstring(text)
        results = []

        def walk(node, month_val, type_val):
            name = (node.get("name") or "").strip()
            if node.tag == "class_2" and name:
                month_val = name
            if node.tag == "class_3" and name:
                type_val = name
            ry, rm, rd = (node.findtext("release_year"),
                          node.findtext("release_month"),
                          node.findtext("release_day"))
            if ry and rm and rd:
                try:
                    is_today = (int(ry), int(rm), int(rd)) == (today.year, today.month, today.day)
                except ValueError:
                    is_today = False
                if is_today:
                    h = (node.findtext("release_hour") or "").strip()
                    mi = (node.findtext("release_minute") or "").strip()
                    if h.isdigit() and mi.isdigit():
                        time_val = f"{int(h)}:{int(mi):02d}"
                    else:
                        time_val = "時刻未定"
                    results.append({
                        "time": time_val,
                        "type": type_val or "公表",
                        "month": month_val,
                    })
            for ch in node:
                walk(ch, month_val, type_val)

        walk(root, "", "")
        return results
    except Exception as e:
        print(f"XML取得エラー: {e}")
        return []


def send_discord(events):
    today = _today_jst().isoformat()
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

    today = _today_jst().isoformat()
    print(f"実行日(JST): {today}")

    events = check_publication_day()
    if events:
        print(f"本日は公表日です: {[e['type'] for e in events]}")
        send_discord(events)
    else:
        print("本日は公表日ではありません")


if __name__ == "__main__":
    main()
