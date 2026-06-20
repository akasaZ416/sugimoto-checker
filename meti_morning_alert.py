"""
meti_morning_alert.py
毎朝実行。今日(JST)が生産動態統計の公表日（速報・確報どちらも）なら Discord に通知する。

■ なぜ同梱スケジュール方式なのか（重要）
  当初は実行のたびに METI の公表予定XMLを直接取得していたが、GitHub Actions の
  ランナーIP(海外DC)からは www.meti.go.jp が読み取りタイムアウトでほぼ常に到達不能。
  旧コードはこの取得失敗を握りつぶして「公表日ではない」と誤判定しており、
  速報も確報も実際には一度も通知できていなかった（2026-06 のログで判明）。
  外部CORSプロキシ各種も METI に到達できず全滅。
  → そこで「公表予定はほぼ年単位で固定」という性質を使い、スケジュールを
    meti_schedule.json として同梱し、ネット非依存で判定する方式に変更した。
    取得はベストエフォートで試み、成功した時だけ最新化する（自己更新）。

■ スケジュールの更新
  meti_schedule.json は META に到達できる環境（ローカルPC等、build_schedule_json
  参照）で再生成してコミットすれば最新化される。GitHub 上でも、たまたま取得に
  成功した日は新しい内容で上書きし、ワークフローがコミットして反映する。
"""
import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# METI の公表日は JST の暦日。ランナーは UTC で動くため必ず JST で today を取る。
JST = timezone(timedelta(hours=9))


def _today_jst():
    return datetime.now(JST).date()


DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
XML_URL = "https://www.meti.go.jp/statistics/tyo/seidou/yotei/xml/e-stat_seidou.xml"
RESULT_PAGE_URL = "https://www.meti.go.jp/statistics/tyo/seidou/result/ichiran/08_seidou.html"
SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meti_schedule.json")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}
# ベストエフォート取得。届かないのが常態なので短く・少なく（失敗しても同梱JSONで判定）。
FETCH_TIMEOUT = (10, 20)
FETCH_RETRIES = 2


def parse_schedule_xml(text):
    """公表予定XMLテキストを [{date,time,type,month}, ...] に変換する。"""
    root = ET.fromstring(text)
    out = []

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
                date_str = f"{int(ry):04d}-{int(rm):02d}-{int(rd):02d}"
            except ValueError:
                date_str = None
            if date_str:
                h = (node.findtext("release_hour") or "").strip()
                mi = (node.findtext("release_minute") or "").strip()
                time_val = f"{int(h)}:{int(mi):02d}" if h.isdigit() and mi.isdigit() else "時刻未定"
                out.append({"date": date_str, "time": time_val,
                            "type": type_val or "公表", "month": month_val})
        for ch in node:
            walk(ch, month_val, type_val)

    walk(root, "", "")
    out.sort(key=lambda x: x["date"])
    return out


def try_fetch_fresh():
    """METI から最新の公表予定を取得してエントリ配列を返す。
    到達できない（=常態）場合は None を返す（例外にしない）。"""
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            r = requests.get(XML_URL, headers=HEADERS, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            try:
                text = r.content.decode("utf-16")
            except UnicodeError:
                text = r.text
            entries = parse_schedule_xml(text)
            if entries:
                print(f"最新の公表予定を取得しました（{len(entries)}件）")
                return entries
        except Exception as e:
            print(f"最新取得は失敗 (試行 {attempt}/{FETCH_RETRIES}): {e}")
            if attempt < FETCH_RETRIES:
                time.sleep(5)
    print("最新取得できず → 同梱スケジュールで判定します")
    return None


def load_bundled_schedule():
    """同梱の meti_schedule.json からエントリ配列を読む。"""
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("entries", [])


def save_schedule(entries):
    """最新取得に成功したらスケジュールを上書き保存（自己更新）。"""
    data = {
        "_source": XML_URL,
        "_note": ("生産動態統計 公表予定。GitHubランナーからMETIに到達できないため同梱。"
                  "到達できる環境で再取得して更新する。"),
        "entries": entries,
    }
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_schedule():
    """最新取得を試し、成功すれば上書き保存して返す。失敗時は同梱JSONを返す。"""
    fresh = try_fetch_fresh()
    if fresh:
        try:
            bundled = load_bundled_schedule()
        except Exception:
            bundled = None
        if fresh != bundled:
            save_schedule(fresh)
            print("同梱スケジュールを更新しました")
        return fresh
    return load_bundled_schedule()


def todays_events(schedule):
    today = _today_jst().isoformat()
    return [e for e in schedule if e.get("date") == today]


def send_discord(events):
    today = _today_jst().isoformat()
    embeds = []
    for e in events:
        month_str = f"（{e['month']}）" if e.get("month") else ""
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

    print(f"実行日(JST): {_today_jst().isoformat()}")

    try:
        schedule = get_schedule()
    except Exception as e:
        # 同梱JSONすら読めない異常時のみエラー通知（通常起きない）。
        print(f"スケジュール取得に失敗: {e}")
        if DISCORD_WEBHOOK:
            try:
                requests.post(DISCORD_WEBHOOK, json={"embeds": [{
                    "title": "⚠️ 生産動態統計 公表予定の読み込みに失敗しました",
                    "description": (f"公表予定の判定ができませんでした。手動で確認してください。\n"
                                    f"🔗 [公表ページ]({RESULT_PAGE_URL}#menu1)\n\n```{str(e)[:300]}```"),
                    "color": 0xCC3300,
                }]}, timeout=10)
            except Exception:
                pass
        exit(1)

    events = todays_events(schedule)
    if events:
        print(f"本日は公表日です: {[e['type'] for e in events]}")
        send_discord(events)
    else:
        print("本日は公表日ではありません")


if __name__ == "__main__":
    main()
