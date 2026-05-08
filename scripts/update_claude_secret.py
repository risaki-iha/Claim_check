"""
ローカル実行用：~/.claude/.credentials.json を読み取って GitHub Secrets を最新化する。

amptalk-risk-detection の同名スクリプトと同じ仕組み。

使い方:
    py scripts/update_claude_secret.py

前提:
- gh CLI 認証済み
- このリポジトリのディレクトリで実行
"""

import json
import os
import subprocess
import sys
from pathlib import Path


CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
REPO = "risaki-iha/Claim_check"


def main():
    if not CREDENTIALS_PATH.exists():
        print(f"❌ {CREDENTIALS_PATH} が存在しません。Claude Code でログイン済みか確認してください。")
        sys.exit(1)

    raw = CREDENTIALS_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)

    # 構造はバージョンによって変わるので柔軟に
    # 例: { "claudeAiOauth": { "refreshToken": "...", "accessToken": "..." } }
    refresh_token = (
        data.get("claudeAiOauth", {}).get("refreshToken")
        or data.get("refresh_token")
    )
    if not refresh_token:
        print("❌ refresh_token が見つかりません。.credentials.json の構造を確認してください。")
        print("   キー候補: claudeAiOauth.refreshToken / refresh_token")
        sys.exit(1)

    set_secret("CLAUDE_REFRESH_TOKEN", refresh_token)
    set_secret("CLAUDE_CREDENTIALS", raw)
    print("✅ GitHub Secrets を更新しました")


def set_secret(name: str, value: str):
    print(f"  → {name} を更新...")
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--repo", REPO],
        input=value,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(f"  ❌ {name} の更新失敗: {proc.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
