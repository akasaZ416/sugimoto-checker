"""
tsmc_notify.py
毎朝8:30実行：
  - 毎月1日 → カレンダー更新リマインダーをDiscordに送信
  - 毎日    → 当日のTSMCイベントがあればDiscordに通知
"""
import json
import os
import requests
from datetime import date

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
CALENDAR_FILE = "tsmc_calendar.json"
TSMC_CALENDAR_URL = "https://investor.tsmc.com/japanese/financial-calendar"

EMOJI = {"monthly": "📊", "earnings": "💹"}
COLOR = {"monthly": 0x00aaff, "earnings": 0xff8800}


def load_todays_events():
    if not os.path.exists(CALENDAR_FILE):
        print(f"WARNING: {CALENDAR_FILE} が見つかりません")
        return []
    with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
        events = json.load(f)
    today = date.today().isoformat()
    return [e for e in events if e["date"] == today]


def send_update_reminder():
    """毎月1日：カレンダー更新リマインダーを送信"""
    today = date.today()
    payload = {
        "embeds": [{
            "title": "🗓️ TSMCカレンダーの確認をお願いします",
            "description": (
                f"今月（{today.year}年{today.month}月）の発表日程を確認し、\n"
                f"`tsmc_calendar.json` を必要に応じて更新してください。\n\n"
                f"🔗 [TSMC公式 財務カレンダー]({TSMC_CALENDAR_URL})"
            ),
            "color": 0x888888,
            "footer": {"text": "毎月1日の自動リマインダー"},
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    print("更新リマインダーを送信しました")


def send_event_notification(events):
    """当日イベントをDiscordに通知"""
    embeds = []
    for e in events:
        emoji = EMOJI.get(e["type"], "📅")
        color = COLOR.get(e["type"], 0x888888)
        embeds.append({
            "title": f"{emoji} 本日のTSMCイベント",
            "description": (
                f"**{e['label']}**\n"
                f"🕐 {e['time']}\n"
                f"🔗 [IRページを確認する]({e['url']})"
            ),
            "color": color,
            "footer": {"text": f"📅 {e['date']}  |  TSMC投資家向け情報"},
        })
    r = requests.post(DISCORD_WEBHOOK, json={"embeds": embeds[:10]}, timeout=10)
    r.raise_for_status()
    print(f"イベント通知を送信しました（{len(embeds)}件）")


def main():
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        exit(1)

    today = date.today()
    print(f"実行日: {today.isoformat()}")

    # 毎月1日はリマインダーを送る
    if today.day == 1:
        print("月初リマインダーを送信します...")
        send_update_reminder()

    # 当日イベントをチェック
    events = load_todays_events()
    if events:
        print(f"本日のイベントが {len(events)} 件あります:")
        for e in events:
            print(f"  - {e['label']} ({e['time']})")
        send_event_notification(events)
    else:
        print("本日のTSMCイベントはありません")


if __name__ == "__main__":
    main()
