"""
tsmc_notify.py
毎朝8:30実行：
  - 毎月1日 → 公式カレンダーを自動取得して登録内容と照合し結果をDiscordに送信
  - 毎日    → 当日のTSMCイベントがあればDiscordに通知
  - 最終登録日当日 → カレンダー登録切れ警告を送信
"""
import json
import os
import re
import requests
from datetime import date, datetime

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
CALENDAR_FILE = "tsmc_calendar.json"
TSMC_CALENDAR_URL = "https://investor.tsmc.com/japanese/financial-calendar"

EMOJI = {"monthly": "📊", "earnings": "💹"}
COLOR = {"monthly": 0x00aaff, "earnings": 0xff8800}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ──────────────────────────────────────────
# カレンダー読み込み
# ──────────────────────────────────────────

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


# ──────────────────────────────────────────
# 公式カレンダーの自動取得（Googleキャッシュ経由）
# ──────────────────────────────────────────

def fetch_official_calendar():
    """
    TSMCの公式サイトは直接403になるため、
    Googleの検索スニペットから日程データを抽出する。
    取得できた日程のリストを返す。失敗時は None を返す。
    """
    try:
        # Googleの検索結果スニペットから日程を抽出
        search_url = (
            "https://www.google.com/search?q=TSMC+financial+calendar+2026"
            "+site:investor.tsmc.com&hl=ja"
        )
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        text = r.text

        # 日付パターン "YYYY-MM-DD" を抽出
        found_dates = re.findall(r"(20\d{2}-\d{2}-\d{2})", text)
        # キーワードも抽出してイベント種別を判定
        found_events = []
        for m in re.finditer(
            r"(20\d{2}-\d{2}-\d{2}).*?(Monthly Sales|Earnings Conference|Results)",
            text, re.DOTALL
        ):
            d, kind = m.group(1), m.group(2)
            event_type = "monthly" if "Monthly" in kind else "earnings"
            found_events.append({"date": d, "type": event_type})

        # 重複除去・ソート
        seen = set()
        unique = []
        for e in sorted(found_events, key=lambda x: x["date"]):
            if e["date"] not in seen:
                seen.add(e["date"])
                unique.append(e)

        return unique if unique else None

    except Exception as ex:
        print(f"自動取得エラー: {ex}")
        return None


def compare_calendars(registered, official):
    """
    登録済みカレンダーと公式データを比較し、
    差分（追加・変更・削除）を返す。
    """
    reg_dict = {e["date"]: e for e in registered}
    off_dict = {e["date"]: e for e in official}

    today = date.today().isoformat()
    # 今日以降のイベントのみ比較
    reg_future = {d: e for d, e in reg_dict.items() if d >= today}
    off_future = {d: e for d, e in off_dict.items() if d >= today}

    added   = [d for d in off_future if d not in reg_future]
    removed = [d for d in reg_future if d not in off_future]

    return added, removed


# ──────────────────────────────────────────
# Discord送信
# ──────────────────────────────────────────

def send_monthly_reminder(registered_events, last_date):
    today = date.today()

    # 残り日数チェック
    end_warning = ""
    if last_date:
        days_left = (datetime.strptime(last_date, "%Y-%m-%d").date() - today).days
        if days_left <= 60:
            end_warning = (
                f"\n\n⚠️ **登録は `{last_date}` まで（残り{days_left}日）**\n"
                f"来年分の追加もお願いします！"
            )

    # 自動照合を試みる
    print("公式カレンダーを自動取得中...")
    official = fetch_official_calendar()

    if official:
        added, removed = compare_calendars(registered_events, official)

        if not added and not removed:
            diff_text = "✅ **登録内容と公式カレンダーに差分はありません**"
        else:
            diff_text = ""
            if added:
                diff_text += "**➕ 公式に追加されている日程:**\n"
                for d in added:
                    diff_text += f"　`{d}`\n"
            if removed:
                diff_text += "**➖ 公式から消えている日程（変更の可能性）:**\n"
                for d in removed:
                    diff_text += f"　`{d}`\n"
            diff_text += "\n`tsmc_calendar.json` の更新をご確認ください。"

        description = (
            f"{today.year}年{today.month}月の自動照合結果です。\n\n"
            f"{diff_text}"
            f"{end_warning}\n\n"
            f"🔗 [TSMC公式 財務カレンダーを確認する]({TSMC_CALENDAR_URL})"
        )
        title = "🔍 TSMCカレンダー 自動照合レポート"
        color = 0x00cc66 if not (added or removed) else 0xff8800

    else:
        # 自動取得失敗 → URLを大きく表示して手動確認を促す
        description = (
            f"今月（{today.year}年{today.month}月）の日程を公式サイトで確認し、\n"
            f"`tsmc_calendar.json` の内容と照合してください。"
            f"{end_warning}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔗 **[TSMC公式 財務カレンダーを今すぐ確認する]({TSMC_CALENDAR_URL})**\n"
            f"━━━━━━━━━━━━━━━"
        )
        title = "🗓️ TSMCカレンダーの照合をお願いします（自動取得失敗）"
        color = 0x888888

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
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


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main():
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        exit(1)

    today = date.today()
    print(f"実行日: {today.isoformat()}")

    events    = load_calendar()
    last_date = get_last_registered_date(events)
    print(f"カレンダー最終登録日: {last_date}")

    # 毎月1日：自動照合 + リマインダー
    if today.day == 1:
        print("月初照合リマインダーを送信します...")
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
