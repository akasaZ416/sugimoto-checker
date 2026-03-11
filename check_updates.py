import requests
import hashlib
import os
import sys
import json
import difflib
from datetime import datetime
from bs4 import BeautifulSoup

SITE_ID = sys.argv[1] if len(sys.argv) > 1 else "unknown"

SITES = {
    "sugimoto": {
        "url": "https://www.e-sugimoto.co.jp/products/information/",
        "name": "杉本商事 価格改定・供給情報",
        "mode": "table",  # テーブル構造を解析するモード
    },
    "jraia": {
        "url": "https://www.jraia.or.jp/statistic/detail.html?ca=0&ca2=0",
        "name": "日冷工 統計データ",
        "mode": "text",
    },
    "jcma": {
        "url": "https://www.jcma2.jp/toukei/index.html",
        "name": "日本冷凍空調工事工業会 統計",
        "mode": "text",
    },
    "mizuho": {
        "url": "https://www.mizuho-rt.co.jp/business/research/index.html",
        "name": "みずほリサーチ&テクノロジーズ リサーチレポート",
        "mode": "text",
    },
}

if SITE_ID not in SITES:
    print(f"ERROR: 不明なサイトID '{SITE_ID}'。使用可能: {list(SITES.keys())}")
    sys.exit(1)

SITE = SITES[SITE_ID]
URL = SITE["url"]
SITE_NAME = SITE["name"]
MODE = SITE["mode"]
HASH_FILE = f"last_hash_{SITE_ID}.txt"
CONTENT_FILE = f"last_content_{SITE_ID}.txt"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")


def fetch_html():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; UpdateChecker/1.0)"}
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


# ─── テーブルモード（杉本商事専用） ───────────────────────────────

def parse_table(html):
    """テーブルを {メーカー名: {カテゴリー, 価格改定情報, 商品供給情報}} の辞書に変換"""
    soup = BeautifulSoup(html, "html.parser")
    rows = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all("td")]
            if len(cells) >= 2 and cells[0] and cells[0] not in ("メーカー名",):
                maker = cells[0]
                category = cells[1] if len(cells) > 1 else ""
                price_info = cells[2] if len(cells) > 2 else ""
                supply_info = cells[3] if len(cells) > 3 else ""
                # 同一メーカーが複数カテゴリーを持つ場合はキーを区別
                key = f"{maker}｜{category}" if category else maker
                rows[key] = {
                    "メーカー名": maker,
                    "カテゴリー": category,
                    "価格改定情報": price_info,
                    "商品供給情報": supply_info,
                }
    return rows


def build_table_diff(old_json_str, new_json_str):
    old = json.loads(old_json_str) if old_json_str else {}
    new = json.loads(new_json_str)

    added_keys = set(new.keys()) - set(old.keys())
    removed_keys = set(old.keys()) - set(new.keys())
    changed_keys = {
        k for k in set(new.keys()) & set(old.keys())
        if new[k] != old[k]
    }

    lines = []

    if added_keys:
        lines.append("**➕ 新たに追加されたメーカー・行:**")
        for k in sorted(added_keys):
            r = new[k]
            lines.append(f"　📌 **{r['メーカー名']}**（{r['カテゴリー']}）")
            if r["価格改定情報"] and r["価格改定情報"] != "-":
                lines.append(f"　　💴 価格改定: {r['価格改定情報'][:120]}")
            if r["商品供給情報"] and r["商品供給情報"] != "-":
                lines.append(f"　　📦 供給情報: {r['商品供給情報'][:120]}")

    if removed_keys:
        lines.append("**➖ 削除されたメーカー・行:**")
        for k in sorted(removed_keys):
            r = old[k]
            lines.append(f"　📌 **{r['メーカー名']}**（{r['カテゴリー']}）")

    if changed_keys:
        lines.append("**🔄 変更されたメーカー・行:**")
        for k in sorted(changed_keys):
            old_r = old[k]
            new_r = new[k]
            lines.append(f"　📌 **{new_r['メーカー名']}**（{new_r['カテゴリー']}）")
            for col in ["価格改定情報", "商品供給情報"]:
                if old_r[col] != new_r[col]:
                    lines.append(f"　　【{col}】変更あり")
                    # 追加されたテキストを簡易表示
                    old_words = set(old_r[col].split())
                    new_words = set(new_r[col].split())
                    added_words = new_words - old_words
                    if added_words:
                        added_preview = " ".join(list(added_words)[:20])
                        lines.append(f"　　　＋ {added_preview[:120]}")

    if not lines:
        lines.append("変更箇所を特定できませんでした（見えない部分の変更の可能性があります）")

    return "\n".join(lines)


def get_table_content(html):
    rows = parse_table(html)
    return json.dumps(rows, ensure_ascii=False)


# ─── テキストモード（その他サイト） ────────────────────────────────

def get_text_content(html):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup.find("article") or soup.find("body")
    return main.get_text(strip=True, separator="\n") if main else html


def build_text_diff(old_content, new_content):
    old_lines = [l for l in old_content.splitlines() if l.strip()]
    new_lines = [l for l in new_content.splitlines() if l.strip()]
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    added = [l[1:].strip() for l in diff if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:].strip() for l in diff if l.startswith("-") and not l.startswith("---")]
    summary = ""
    if added:
        summary += "**➕ 追加された内容:**\n"
        for line in added[:10]:
            if line:
                summary += f"```{line[:100]}```\n"
    if removed:
        summary += "**➖ 削除された内容:**\n"
        for line in removed[:10]:
            if line:
                summary += f"```{line[:100]}```\n"
    if not summary:
        summary = "変更箇所を特定できませんでした"
    return summary


# ─── 共通処理 ──────────────────────────────────────────────────────

def get_hash(content):
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def load_last_hash():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            return f.read().strip()
    return None


def save_hash(h):
    with open(HASH_FILE, "w") as f:
        f.write(h)


def load_last_content():
    if os.path.exists(CONTENT_FILE):
        with open(CONTENT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def save_content(content):
    with open(CONTENT_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def send_discord_notification(diff_summary):
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        return
    if len(diff_summary) > 3000:
        diff_summary = diff_summary[:3000] + "\n...（省略）"
    payload = {
        "embeds": [{
            "title": f"🔔 {SITE_NAME} が更新されました！",
            "description": f"更新を検知しました。\n[サイトを確認する]({URL})\n\n{diff_summary}",
            "color": 0x00aaff,
            "footer": {"text": f"確認日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
        }]
    }
    response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    response.raise_for_status()
    print("Discord通知を送信しました")


def main():
    print(f"サイトを確認中: {URL}（モード: {MODE}）")
    try:
        html = fetch_html()

        if MODE == "table":
            current_content = get_table_content(html)
        else:
            current_content = get_text_content(html)

        current_hash = get_hash(current_content)
        last_hash = load_last_hash()

        print(f"現在のハッシュ: {current_hash}")
        print(f"前回のハッシュ: {last_hash}")

        if last_hash is None:
            print("初回実行: データを保存しました")
            save_hash(current_hash)
            save_content(current_content)
        elif current_hash != last_hash:
            print("✅ 更新を検知しました！")
            old_content = load_last_content()

            if MODE == "table":
                diff_summary = build_table_diff(old_content, current_content)
            else:
                diff_summary = build_text_diff(old_content, current_content)

            print(f"差分:\n{diff_summary}")
            send_discord_notification(diff_summary)
            save_hash(current_hash)
            save_content(current_content)
        else:
            print("変更なし")

    except Exception as e:
        print(f"エラーが発生しました: {e}")
        raise


if __name__ == "__main__":
    main()
