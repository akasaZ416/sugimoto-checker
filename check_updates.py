import requests
import hashlib
import os
import difflib
from datetime import datetime
from bs4 import BeautifulSoup

URL = "https://www.e-sugimoto.co.jp/products/information/"
HASH_FILE = "last_hash.txt"
CONTENT_FILE = "last_content.txt"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

def get_page_content():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; UpdateChecker/1.0)"}
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    main = soup.find("main") or soup.find("article") or soup.find("body")
    return main.get_text(strip=True, separator="\n") if main else response.text

def get_hash(content):
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def load_last_hash():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            return f.read().strip()
    return None

def save_hash(hash_value):
    with open(HASH_FILE, "w") as f:
        f.write(hash_value)

def load_last_content():
    if os.path.exists(CONTENT_FILE):
        with open(CONTENT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_content(content):
    with open(CONTENT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def build_diff_summary(old_content, new_content):
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
        summary = "変更箇所を特定できませんでした（レイアウトや見えない部分の変更の可能性があります）"
    
    return summary

def send_discord_notification(diff_summary):
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        return
    
    if len(diff_summary) > 3000:
        diff_summary = diff_summary[:3000] + "\n...（省略）"
    
    payload = {
        "embeds": [{
            "title": "🔔 杉本商事 商品情報が更新されました！",
            "description": f"更新を検知しました。\n[サイトを確認する]({URL})\n\n{diff_summary}",
            "color": 0x00aaff,
            "footer": {"text": f"確認日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
        }]
    }
    
    response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    response.raise_for_status()
    print("Discord通知を送信しました")

def main():
    print(f"サイトを確認中: {URL}")
    
    try:
        content = get_page_content()
        current_hash = get_hash(content)
        last_hash = load_last_hash()
        
        print(f"現在のハッシュ: {current_hash}")
        print(f"前回のハッシュ: {last_hash}")
        
        if last_hash is None:
            print("初回実行: ハッシュとコンテンツを保存しました")
            save_hash(current_hash)
            save_content(content)
        elif current_hash != last_hash:
            print("✅ 更新を検知しました！")
            old_content = load_last_content()
            diff_summary = build_diff_summary(old_content, content)
            print(f"差分:\n{diff_summary}")
            send_discord_notification(diff_summary)
            save_hash(current_hash)
            save_content(content)
        else:
            print("変更なし")
            
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        raise

if __name__ == "__main__":
    main()
