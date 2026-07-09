"""
上長メンション解決（マスタスプシから AM 上長を引く）

設計方針:
- マスタスプシ「1_顧客一覧」を読み、channel_id / 顧客NO / 顧客名セグメント → (マネ名, マネメアド) の辞書を作る
- 検知チャンネルの突合は3段構え（上から優先）:
    ① channel_id (K列) 完全マッチ           … 実IDで最も確実
    ② 顧客NO 6桁本体マッチ (F列「顧客窓口No」) … チャンネル名から最後の6桁を抽出して突合。枝番ズレ/欠落を吸収
    ③ 顧客名 (D列) でチャンネル名部分マッチ  … 最後の保険（誤爆しうるので最後）
  ②について: 顧客窓口No は `XXXXXX-XXX`（6桁本体＋3桁窓口枝番）。チャンネル名末尾の枝番がズレる/欠けることがある
  ため、突合キーは6桁本体のみを使う。同一6桁本体で担当AMが異なるケースは実スプシで0件確認済み。
- 解決したマネのメアド (I列) を Slack の users.list 由来の email → user_id 辞書から user_id に変換してメンション化
- メアドで引けなければマネ名 (H列) → user_id 辞書をフォールバック
- 一覧で引けない / user_id を解決できない全ケースは DEFAULT_MENTION_EMAIL（宮澤）にフォールバック
- 宮澤すら user_id を引けなければ None（呼び出し側で【マネージャー】行を出さない＝事故メンション防止）
"""

import json
import os
import re

import gspread
from google.oauth2.service_account import Credentials

MASTER_SPREADSHEET_ID = "1PWqW08yD6shJu5sRUxTZvf7w7K7TaJEuQcDU2QmkZXY"
MASTER_SHEET_NAME = "1_顧客一覧"

# 一覧にいない案件、または一覧にはいるが user_id を解決できなかった案件の
# 上長メンション フォールバック先（宮澤）。
DEFAULT_MENTION_EMAIL = "toru_my@nyle.co.jp"

# データ行は5行目(1-indexed)から。1〜4行目は注釈/見出し。
DATA_START_ROW_INDEX = 4
COL_CALL_NAME = 1      # B列（コール名検索）
COL_CUSTOMER_NAME = 3  # D列（顧客名）
COL_KOKYAKU_NO = 5     # F列（顧客窓口No ※ XXXXXX-XXX 形式）
COL_MANAGER = 7        # H列（slackメンション先 ※マネ）
COL_EMAIL = 8          # I列（MGメアド）
COL_SLACK_CH_ID = 10   # K列（slackチャンネルID）

# 顧客NO 6桁本体を抽出。複数あれば最後の出現を採用（NOは名前の末尾寄りにある前提）。
# 例: '社内_楽天-gora_100093-003' → '100093'
#     '社内_プライムクロス_100706'  → '100706'
_KOKYAKU_RE = re.compile(r"(?<!\d)(\d{6})(?:-\d+)?(?!\d)")


def extract_kokyaku_base(text: str) -> str | None:
    if not text:
        return None
    matches = _KOKYAKU_RE.findall(text)
    return matches[-1] if matches else None


class SupervisorResolver:
    def __init__(self):
        self._by_channel_id: dict[str, dict[str, str]] = {}
        self._by_kokyaku_base: dict[str, dict[str, str]] = {}
        self._by_customer_name: list[tuple[str, dict[str, str]]] = []
        self._loaded = False

    def load(self, gc: gspread.Client | None = None) -> None:
        if gc is None:
            gc = _build_gspread_client()
        ws = gc.open_by_key(MASTER_SPREADSHEET_ID).worksheet(MASTER_SHEET_NAME)
        rows = ws.get_all_values()
        self.load_from_rows(rows)

    def load_from_rows(self, rows: list[list[str]]) -> None:
        """テスト用：rows を直接受け取って辞書を構築する。"""
        for i, row in enumerate(rows):
            if i < DATA_START_ROW_INDEX:
                continue
            # 短い行はスキップ（必要な列まで届かないため）
            if len(row) <= COL_SLACK_CH_ID:
                continue
            customer_name = (row[COL_CUSTOMER_NAME] or "").strip()
            kokyaku_no = (row[COL_KOKYAKU_NO] or "").strip() if len(row) > COL_KOKYAKU_NO else ""
            manager = (row[COL_MANAGER] or "").strip()
            email = (row[COL_EMAIL] or "").strip()
            ch_id = (row[COL_SLACK_CH_ID] or "").strip()
            if not manager and not email:
                continue
            entry = {"name": manager, "email": email}
            if ch_id:
                self._by_channel_id[ch_id] = entry
            base = extract_kokyaku_base(kokyaku_no)
            if base:
                self._by_kokyaku_base.setdefault(base, entry)
            if customer_name:
                self._by_customer_name.append((customer_name, entry))
        self._loaded = True

    def resolve_entry(self, channel_id: str, channel_name: str) -> dict | None:
        if not self._loaded:
            return None
        # ① channel_id 完全マッチ
        if channel_id:
            entry = self._by_channel_id.get(channel_id)
            if entry:
                return entry
        # ② 顧客NO 6桁本体マッチ（枝番ズレ/欠落を吸収）
        if channel_name:
            base = extract_kokyaku_base(channel_name)
            if base:
                entry = self._by_kokyaku_base.get(base)
                if entry:
                    return entry
        # ③ 顧客名セグメント部分マッチ（最後の保険）
        if channel_name:
            segments = [s for s in channel_name.split("_") if len(s) >= 3]
            for customer_name, entry in self._by_customer_name:
                if any(seg in customer_name for seg in segments):
                    return entry
        return None

    def resolve_mention(
        self,
        channel_id: str,
        channel_name: str,
        user_id_by_name: dict,
        user_id_by_email: dict,
        default_email: str | None = None,
    ) -> str | None:
        """
        検知チャンネル → Slack メンション文字列 (<@U0XXX>) を返す。
        メアド(E列)からの解決を優先、名前(D列)はフォールバック。
        一覧で引けない / user_id を解決できない場合は default_email（宮澤）で再解決する。
        それでも引けなければ None。
        """
        entry = self.resolve_entry(channel_id, channel_name)
        if entry:
            email = entry.get("email", "")
            if email:
                uid = user_id_by_email.get(email)
                print(f"[supervisor] ch={channel_id!r} entry_email={email!r} uid={uid!r}", flush=True)
                if uid:
                    return f"<@{uid}>"
            name = entry.get("name", "")
            if name:
                uid = user_id_by_name.get(name)
                print(f"[supervisor] ch={channel_id!r} entry_name={name!r} uid={uid!r}", flush=True)
                if uid:
                    return f"<@{uid}>"
        else:
            print(f"[supervisor] ch={channel_id!r} name={channel_name!r} → no entry found", flush=True)
        # 一覧外 or user_id 解決不能 → 宮澤にフォールバック
        if default_email:
            uid = user_id_by_email.get(default_email)
            if uid:
                return f"<@{uid}>"
        return None


def _build_gspread_client() -> gspread.Client:
    sa_json = os.environ.get("GOOGLE_SHEETS_KEY")
    if not sa_json:
        raise RuntimeError("GOOGLE_SHEETS_KEY 環境変数が必要（サービスアカウント JSON）")
    creds_dict = json.loads(sa_json.lstrip("﻿"))
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)
