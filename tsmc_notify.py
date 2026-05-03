"""
tsmc_notify.py
毎朝8:30実行：
  - 毎月1日 → カレンダー照合リマインダーをDiscordに送信
  - 毎日    → 当日のTSMCイベントがあればDiscordに通知
  - 最終登録日当日 → カレンダー登録切れ警告を送信
"""
import json
import os
import requests
from datetime import date, datetime

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
CALENDAR_FILE = "tsmc_calendar.json"
TSMC_CALENDAR_URL = "https://investor.tsmc.com/japanese/financial-calendar"

EMOJI = {"monthly": "📊", "earnings": "💹"}
COLOR = {"monthly": 0x00aaff, "earnings": 0xff8800}


def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        print(f"WARNING: {CALENDAR_FILE} が見つかりません")
        return []
    with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_todays_events(events):
    return [e for e in events if e["date"] == date.today().isoformat()]


def get_last_registered_date(events):
    if not events:
        return None
    return max(e["date"] for e in events)


def send_monthly_reminder(events, last_date):
    today = date.today()

    # 直近3ヶ月以内のイベントを一覧表示
    upcoming = [e for e in events if e["date"] >= today.isoformat()]
    upcoming = sorted(upcoming, key=lambda x: x["date"])[:6]  # 最大6件

    upcoming_text = ""
    if upcoming:
        upcoming_text = "\n**📋 登録済みの直近イベント:**\n"
        for e in upcoming:
            emoji = EMOJI.get(e["type"], "📅")
            upcoming_text += f"　{emoji} `{e['date']}` {e['label']}\n"
    else:
        upcoming_text = "\n⚠️ **登録済みの今後のイベントがありません！**\n"

    end_warning = ""
    if last_date:
        days_left = (datetime.strptime(last_date, "%Y-%m-%d").date() - today).days
        if days_left <= 60:
            end_warning = (
                f"\n⚠️ **登録は `{last_date}` まで（残り{days_left}日）**\n"
                f"来年分の追加もお願いします！"
            )

    payload = {
        "embeds": [{
            "title": "🗓️ TSMCカレンダー 月次確認",
            "description": (
                f"今月（{today.year}年{today.month}月）の日程を公式サイトと照合してください。"
                f"{upcoming_text}"
                f"{end_warning}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🔗 **[TSMC公式 財務カレンダーを今すぐ確認する]({TSMC_CALENDAR_URL})**\n"
                f"━━━━━━━━━━━━━━━"
            ),
            "color": 0x888888,
            "footer": {"text": f"毎月1日の自動リマインダー | {today.isoformat()}"},
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    print("月初リマインダーを送信しました")


def send_end_of_calendar_warning(last_date):
    payload = {
        "embeds": [{
            "title": "⚠️ TSMCカレンダーの登録が今日で終わりです",
            "description": (
                f"本日（`{last_date}`）が `tsmc_calendar.json` の**最後の登録日**です。\n\n"
                f"公式サイトで来年分の日程を確認し、追加してください。\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🔗 **[TSMC公式 財務カレンダーを今すぐ確認する]({TSMC_CALENDAR_URL})**\n"
                f"━━━━━━━━━━━━━━━"
            ),
            "color": 0xff4444,
            "footer": {"text": "カレンダー登録切れ警告"},
        }]
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    print("カレンダー終了警告を送信しました")


def send_event_notification(events):
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

    events = load_calendar()
    last_date = get_last_registered_date(events)
    print(f"カレンダー最終登録日: {last_date}")

    # 毎月1日：リマインダー送信
    if today.day == 1:
        print("月初リマインダーを送信します...")
        send_monthly_reminder(events, last_date)

    # 当日イベントをチェック
    todays_events = load_todays_events(events)
    if todays_events:
        print(f"本日のイベントが {len(todays_events)} 件あります:")
        for e in todays_events:
            print(f"  - {e['label']} ({e['time']})")
        send_event_notification(todays_events)

        # 今日がカレンダーの最終登録日なら警告も送信
        if last_date == today.isoformat():
            print("カレンダーの最終登録日です。警告を送信します...")
            send_end_of_calendar_warning(last_date)
    else:
        print("本日のTSMCイベントはありません")


if __name__ == "__main__":
    main()
