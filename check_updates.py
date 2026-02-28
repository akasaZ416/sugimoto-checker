import requests
import hashlib
import os
import json
from datetime import datetime
from bs4 import BeautifulSoup

URL ="https://www.e-sugimoto.co.jp/products/information/"
HASH_FILE = "last_hash.txt"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

def get_page_content():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; UpdateChecker/1.0)"}
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    # メインコンテンツのみ抽出（ナビゲーション等を除く）
    main = soup.find("main") or soup.find("article") or soup.find("body")
    return main.get_text(strip=True) if main else response.text

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

def send_discord_notification():
    if not DISCORD_WEBHOOK:
        print("ERROR: DISCORD_WEBHOOK_URL が設定されていません")
        return
    
    payload = {
        "embeds": [{
            "title": "🔔 杉本商事 商品情報が更新されました！",
            "description": f"更新を検知しました。\n[サイトを確認する]({URL})",
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
            print("初回実行: ハッシュを保存しました")
            save_hash(current_hash)
        elif current_hash != last_hash:
            print("✅ 更新を検知しました！")
            send_discord_notification()
            save_hash(current_hash)
        else:
            print("変更なし")
            
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        raise

if __name__ == "__main__":
    main()
