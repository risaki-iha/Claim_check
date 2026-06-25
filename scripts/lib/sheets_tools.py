"""
Google Sheets 書き込み（gspread + サービスアカウント）
"""

import os
import json
import time

import gspread
import requests
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials


SPREADSHEET_ID = "1NYuYHOCUM-Uog5VySQ5OiAVkB5HE6_BmYPKpuELqKWI"
SHEET_NAME = "AI検知ログ"

# 列順（A〜L）
COLUMNS = [
    "検知媒体",
    "検知内容",
    "検知日時",
    "チャンネル名",
    "重要度",
    "ステータス",
    "担当者",
    "担当者アドレス",
    "概要",
    "メッセージリンク",
    "スレッド要約",
    "備考",
]


class SheetsTools:
    def __init__(self):
        sa_json = os.environ.get("GOOGLE_SHEETS_KEY")
        if not sa_json:
            raise RuntimeError("GOOGLE_SHEETS_KEY 環境変数が必要（サービスアカウント JSON）")

        # 先頭に BOM (﻿) が混入している場合があるので除去
        creds_dict = json.loads(sa_json.lstrip("﻿"))
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        self.gc = gspread.authorize(creds)
        self.sheet = self.gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

    def append_rows(self, rows: list[dict], max_retries: int = 3) -> int:
        """rows: dict のリスト（key は COLUMNS）

        Google Sheets API は一過性の接続断（RemoteDisconnected 等）や
        5xx / 429 を返すことがある。1発失敗でジョブごと落とさないよう、
        指数バックオフ（1s, 2s, 4s）で最大 max_retries 回リトライする。
        恒久エラー（権限不足などの 4xx）は即座に raise する。
        """
        values = [[row.get(col, "") for col in COLUMNS] for row in rows]
        for attempt in range(max_retries):
            try:
                self.sheet.append_rows(values, value_input_option="USER_ENTERED")
                return len(values)
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                print(
                    f"[sheets] append 失敗（接続系 {attempt + 1}/{max_retries}）: "
                    f"{type(e).__name__} → {wait}s 後リトライ",
                    flush=True,
                )
                time.sleep(wait)
            except APIError as e:
                # 5xx / 429 のみ一過性とみなしリトライ。4xx は即 raise。
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status not in (429, 500, 502, 503, 504) or attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                print(
                    f"[sheets] append 失敗（API {status} {attempt + 1}/{max_retries}）"
                    f" → {wait}s 後リトライ",
                    flush=True,
                )
                time.sleep(wait)
        return 0  # 到達しない（成功で return / 最終失敗で raise）
