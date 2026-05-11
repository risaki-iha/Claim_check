"""
Claude OAuth クライアント

Claude Code サブスクの OAuth トークンを使って Anthropic API を呼ぶ。
これにより Anthropic API の従量課金が発生しない（サブスク内で完結）。

amptalk-risk-detection と同じ仕組み。

仕様:
- 環境変数 CLAUDE_REFRESH_TOKEN からリフレッシュトークンを読む
- リフレッシュエンドポイントで access_token を取得
- Authorization: Bearer <access_token> で Messages API を叩く
- access_token は一定時間有効（expires_in 秒）

自動ローテーション:
- OAuth refresh で新 refresh_token を受け取ったら、環境変数 GH_PAT を使って
  GitHub Secret CLAUDE_REFRESH_TOKEN を上書き更新する（gh CLI 経由）
- GH_PAT 未設定なら警告ログを出して続行（ローカル実行など）

フォールバック:
- ANTHROPIC_API_KEY が設定されてればそちらを使う（従量課金）
"""

import os
import subprocess
import time
import requests

OAUTH_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
GH_SECRET_NAME = "CLAUDE_REFRESH_TOKEN"
GH_DEFAULT_REPO = "risaki-iha/Claim_check"


class ClaudeAuthError(Exception):
    pass


class ClaudeClient:
    """
    OAuth (refresh token) もしくは API キーで Anthropic API を叩く統一クライアント。
    amptalk方式：refresh_token があれば OAuth、無ければ API key にフォールバック。
    """

    def __init__(self):
        self.refresh_token = (os.environ.get("CLAUDE_REFRESH_TOKEN") or "").lstrip("﻿").strip() or None
        self.api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").lstrip("﻿").strip() or None
        self._access_token = None
        self._access_token_expires_at = 0

        if not self.refresh_token and not self.api_key:
            raise ClaudeAuthError(
                "CLAUDE_REFRESH_TOKEN または ANTHROPIC_API_KEY のどちらかが必要"
            )

    def _refresh_access_token(self):
        """OAuth トークンをリフレッシュ。Anthropic OAuth エンドポイントは form-encoded を要求。"""
        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if resp.status_code != 200:
            # JSON フォールバック（古い実装互換）
            resp = requests.post(
                OAUTH_TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": OAUTH_CLIENT_ID,
                },
                timeout=30,
            )
        if resp.status_code != 200:
            raise ClaudeAuthError(
                f"OAuth refresh failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        self._access_token = data["access_token"]
        self._access_token_expires_at = time.time() + data.get("expires_in", 3600) - 60

        # refresh_token がローテーションされる場合は新しい値を採用
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self.refresh_token:
            self.refresh_token = new_refresh
            self._persist_refresh_token(new_refresh)

    def _persist_refresh_token(self, new_token: str) -> None:
        """新 refresh_token を GitHub Secret に書き戻す。GH_PAT 未設定なら警告のみ。"""
        gh_pat = (os.environ.get("GH_PAT") or "").strip()
        if not gh_pat:
            print(
                "[oauth] ⚠️  GH_PAT 未設定のため新 refresh_token を Secret に書き戻せない。"
                "次回実行は invalid_grant で失敗する可能性。",
                flush=True,
            )
            return

        repo = (os.environ.get("GH_REPO") or GH_DEFAULT_REPO).strip()
        try:
            # gh CLI は GH_TOKEN 環境変数で認証できる
            env = {**os.environ, "GH_TOKEN": gh_pat}
            result = subprocess.run(
                ["gh", "secret", "set", GH_SECRET_NAME, "--repo", repo, "--body", new_token],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                print(f"[oauth] ✅ Secret {GH_SECRET_NAME} 更新完了", flush=True)
            else:
                print(
                    f"[oauth] ⚠️  Secret 更新失敗 (code={result.returncode}): {result.stderr[:200]}",
                    flush=True,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[oauth] ⚠️  gh CLI 実行失敗: {e}", flush=True)

    def _ensure_access_token(self):
        if self.refresh_token and (
            not self._access_token or time.time() >= self._access_token_expires_at
        ):
            self._refresh_access_token()

    def _build_headers(self):
        if self.refresh_token:
            self._ensure_access_token()
            return {
                "Authorization": f"Bearer {self._access_token}",
                "anthropic-beta": "oauth-2025-04-20",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def messages_create(
        self,
        *,
        system: str,
        messages: list,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 8000,
        tools: list | None = None,
    ) -> dict:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools

        resp = self._post_with_retry(body)
        if resp.status_code == 401 and self.refresh_token:
            # アクセストークン期限切れの可能性 → 強制リフレッシュして再試行
            self._access_token = None
            resp = self._post_with_retry(body)
        if resp.status_code != 200:
            raise ClaudeAuthError(
                f"Messages API failed: {resp.status_code} {resp.text[:500]}"
            )
        return resp.json()

    def _post_with_retry(self, body: dict, max_retries: int = 4):
        """429 / 5xx に対して指数バックオフでリトライ"""
        delay = 5.0
        for attempt in range(max_retries):
            resp = requests.post(
                MESSAGES_URL, headers=self._build_headers(), json=body, timeout=180
            )
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
            # 429 or 5xx → リトライ
            retry_after = resp.headers.get("retry-after")
            sleep_for = float(retry_after) if retry_after else delay
            print(
                f"[claude retry] status={resp.status_code} attempt={attempt+1}/{max_retries} sleep={sleep_for}s",
                flush=True,
            )
            time.sleep(sleep_for)
            delay *= 2
        return resp

    def get_current_refresh_token(self) -> str:
        """ローテーションされた最新の refresh_token を返す（GitHub Secrets 更新用）"""
        return self.refresh_token
