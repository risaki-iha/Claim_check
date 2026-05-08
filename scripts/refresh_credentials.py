"""
Claude OAuth リフレッシュ実行スクリプト

GitHub Actions で定期的にこれを叩いて、
リフレッシュトークンが期限切れになる前にローテーションする。

ローテーションが発生した場合は、新しい refresh_token を出力して
ワークフロー側で GitHub Secrets を更新する。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.claude_oauth import ClaudeClient


def main():
    client = ClaudeClient()
    if not client.refresh_token:
        print("CLAUDE_REFRESH_TOKEN 未設定。スキップ。", flush=True)
        return

    # ダミーリクエストで access_token を取得（refresh_token のローテーションを誘発）
    client._refresh_access_token()
    new_refresh = client.get_current_refresh_token()
    print("✅ リフレッシュ成功", flush=True)

    # GitHub Actions 上で次の Step に渡す出力
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"new_refresh_token={new_refresh}\n")


if __name__ == "__main__":
    main()
