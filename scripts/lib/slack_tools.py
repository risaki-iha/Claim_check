"""
Slack 操作ラッパー（Bot Token 経由）
"""

import os
import time
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackTools:
    def __init__(self):
        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            raise RuntimeError("SLACK_BOT_TOKEN 環境変数が必要")
        self.client = WebClient(token=token)

    def search(
        self,
        query: str,
        after_ts: int,
        before_ts: int,
        limit: int = 20,
    ) -> list[dict]:
        """
        Slack の search.messages を叩く。
        after/before は Unix秒（JST解釈は呼び出し元）
        """
        # search API は after/before を YYYY-MM-DD で受け取るので変換
        full_query = (
            f"{query} after:{_ymd(after_ts)} before:{_ymd(before_ts)} -is:bot"
        )
        try:
            resp = self.client.search_messages(query=full_query, count=limit, sort="timestamp")
        except SlackApiError as e:
            print(f"[search error] {query}: {e.response['error']}", flush=True)
            return []

        matches = resp.get("messages", {}).get("matches", []) or []
        # ts 範囲で再フィルタ（API の after/before は荒いため）
        out = []
        for m in matches:
            ts = float(m.get("ts", 0))
            if after_ts <= ts < before_ts:
                out.append(m)
        return out

    def read_thread(self, channel: str, thread_ts: str) -> list[dict]:
        try:
            resp = self.client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
            return resp.get("messages", []) or []
        except SlackApiError as e:
            print(f"[read_thread error] {channel}/{thread_ts}: {e.response['error']}", flush=True)
            return []

    def read_user_profile(self, user_id: str) -> dict:
        try:
            resp = self.client.users_info(user=user_id)
            user = resp.get("user", {}) or {}
            profile = user.get("profile", {}) or {}
            return {
                "id": user_id,
                "name": profile.get("display_name") or profile.get("real_name") or user.get("name", ""),
                "email": profile.get("email", ""),
            }
        except SlackApiError as e:
            print(f"[read_user_profile error] {user_id}: {e.response['error']}", flush=True)
            return {"id": user_id, "name": "", "email": ""}

    def read_channel_recent(self, channel: str, limit: int = 50) -> list[dict]:
        try:
            resp = self.client.conversations_history(channel=channel, limit=limit)
            return resp.get("messages", []) or []
        except SlackApiError as e:
            print(f"[read_channel error] {channel}: {e.response['error']}", flush=True)
            return []

    def post_message(self, channel: str, text: str) -> dict:
        try:
            resp = self.client.chat_postMessage(
                channel=channel,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            return {"ok": True, "ts": resp.get("ts")}
        except SlackApiError as e:
            print(f"[post_message error] {channel}: {e.response['error']}", flush=True)
            return {"ok": False, "error": e.response.get("error")}

    def get_channel_info(self, channel: str) -> dict:
        try:
            resp = self.client.conversations_info(channel=channel)
            return resp.get("channel", {}) or {}
        except SlackApiError as e:
            print(f"[get_channel_info error] {channel}: {e.response['error']}", flush=True)
            return {}


def _ymd(ts: int) -> str:
    """Unix秒 → YYYY-MM-DD（JST）"""
    from datetime import datetime, timezone, timedelta
    return datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
