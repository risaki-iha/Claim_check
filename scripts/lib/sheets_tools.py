"""
Google Sheets 書き込み（gspread + サービスアカウント）
"""

import os
import json
import gspread
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

    def append_rows(self, rows: list[dict]) -> int:
        """rows: dict のリスト（key は COLUMNS）"""
        values = [[row.get(col, "") for col in COLUMNS] for row in rows]
        self.sheet.append_rows(values, value_input_option="USER_ENTERED")
        return len(values)
