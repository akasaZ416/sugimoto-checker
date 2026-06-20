"""
meti_morning_alert.py
毎朝8:30に実行。
公表予定XMLを確認して、今日(JST)が公表日であればDiscordに通知する。
速報・確報の区別なく、公表予定日が今日のレコードを全て通知する。

信頼性:
  XML取得が一時的にタイムアウト/失敗すると、以前は結果が空になり「公表日ではない」と
  誤判定して通知を取りこぼしていた（2026-06-12 の4月分確報がこれで通知ゼロだった）。
  対策として (1) 取得をリトライ＋タイムアウト延長、(2) 全リトライ失敗時は
  「公表日ではない」とせず Discord にエラー通知を出す（手動確認を促す）。
"""
import os
import time
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
# METI は素っ気ない UA を時々絞るらしく、海外IP(GitHub Actionsランナー)からは特に遅い。
# 実ブラウザ相当の UA とヘッダを送って通りやすくする。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

# XML取得のリトライ設定。GitHub の海外ランナーからは METI が読み取りタイムアウトしやすい
# （2026-06-12 の4月分確報がこれで通知ゼロだった）。タイムアウトを長く取り、
# 試行間隔も広げて、サーバの一時的な高負荷を数分かけてやり過ごす。
FETCH_TIMEOUT = (15, 60)  # (接続, 読み取り) 秒。読み取りを長めに。
FETCH_RETRIES = 5         # 最大試行回数
FETCH_BACKOFF = 10        # 秒（試行ごとに 10,20,30,40 秒と待ち、計~100秒粘る）


def fetch_schedule_xml():
    """公表予定XMLを取得してテキストを返す。一時的な障害に備えてリトライする。

    全リトライに失敗した場合は例外を送出する（呼び出し側で「公表日ではない」と
    誤判定させず、エラー通知に倒すため）。
    エンコーディングは UTF-16 宣言。requests の自動判定に頼らず明示デコードする。
    """
    last_err = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            r = requests.get(XML_URL, headers=HEADERS, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            try:
                return r.content.decode("utf-16")
            except UnicodeError:
                return r.text
        except Exception as e:
            last_err = e
            print(f"XML取得失敗 (試行 {attempt}/{FETCH_RETRIES}): {e}")
            if attempt < FETCH_RETRIES:
                time.sleep(FETCH_BACKOFF * attempt)
    raise RuntimeError(f"XML取得に{FETCH_RETRIES}回失敗しました: {last_err}")


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

    取得エラーはここでは握りつぶさず、呼び出し側に伝播させる（サイレント取りこぼし防止）。
    """
    today = _today_jst()
    text = fetch_schedule_xml()
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


def send_fetch_error(err):
    """XML取得に失敗したときの通知。沈黙して公表日を取りこぼすより、
    手動確認を促す方が安全。"""
    if not DISCORD_WEBHOOK:
        return
    today = _today_jst().isoformat()
    payload = {"embeds": [{
        "title": "⚠️ 生産動態統計 公表予定の自動確認に失敗しました",
        "description": (
            "公表予定XMLの取得に失敗したため、本日が公表日かどうか判定できませんでした。\n"
            "**確報の公表日を取りこぼしている可能性があります。** お手数ですが手動でご確認ください。\n\n"
            f"🔗 [公表ページ]({RESULT_PAGE_URL}#menu1)\n\n"
            f"```{str(err)[:300]}```"
        ),
        "color": 0xCC3300,
        "footer": {"text": f"📅 {today}  |  経済産業省生産動態統計調査（自動確認エラー）"},
    }]}
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        r.raise_for_status()
        print("取得失敗のエラー通知を送信しました")
    except Exception as e:
        print(f"エラー通知の送信にも失敗: {e}")


def main():
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        exit(1)

    today = _today_jst().isoformat()
    print(f"実行日(JST): {today}")

    try:
        events = check_publication_day()
    except Exception as e:
        # 取得失敗を「公表日ではない」と誤判定しない。取りこぼし防止のため通知を出す。
        print(f"公表日チェックに失敗: {e}")
        send_fetch_error(e)
        exit(1)

    if events:
        print(f"本日は公表日です: {[e['type'] for e in events]}")
        send_discord(events)
    else:
        print("本日は公表日ではありません")


if __name__ == "__main__":
    main()
