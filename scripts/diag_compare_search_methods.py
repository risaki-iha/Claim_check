"""
【診断専用・実害なし】旧方式(search_all_groups=りさきUser Token全文検索)と
新方式(poll_and_match=bot参加チャンネル巡回)を、同じ時間窓で直接比較する。

Slack投稿・スプシ書き込みは一切行わない。標準出力に結果を出すだけ。

目的：
- 2026-07-06/07のbot移行後、検知件数が大幅に減った原因が
  「botの招待漏れ（りさきが見れるchにbotがいない）」なのか、
  「その他の構造的な問題」なのかを実データで切り分ける。
- 両方式の結果を filter_and_dedupe に通した後の差分（旧のみで見つかった
  スレッド）を洗い出し、それぞれのチャンネルにbotが参加しているかを
  突き合わせる。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.slack_tools import SlackTools
from lib.detector import search_all_groups, poll_and_match, filter_and_dedupe, JST
from datetime import datetime, timedelta

# クレーム検知くんのキーワードグループをそのまま流用（run_claim_detection.pyと同一）
KEYWORD_GROUPS = {
    "A": ["クレーム", "謝罪", "申し訳", "ご迷惑", "不信感", "不満",
          "先方からFB", "先方からフィードバック", "早急に改善", "改善必要な状態", "急遽MTG"],
    "B": ["ミス", "遅延", "指摘", "不備", "問題", "確認不足", "対応漏れ",
          "対応遅れ", "連携漏れ", "連携遅れ", "締め切り", "捺印", "検収ズレ",
          "気づかず", "催促", "返事が無い", "返答がない", "返答待ち",
          "チェックバックが遅い", "返信がこない", "連絡がつかない", "連絡が取れない",
          "担当者不在", "担当者が変わった", "日日間違え", "セルがズレ",
          "数値が違う", "計算が違う", "金額が違う", "急すぎ", "納期が短い",
          "着手していない", "対応できません", "リソースが足りない"],
    "C": ["解約", "契約見直し", "予算削減", "費用", "納期", "間に合わ"],
    "D": ["品質", "クオリティ", "齟齬", "懸念", "認識違い", "改善",
          "イマイチ", "やりにくい", "ズレている", "方針が変わった",
          "認識が合っていない", "すり合わせ"],
    "E": ["インデックス", "アクセスできない", "閲覧できない", "移管",
          "障害", "エラー"],
}


def main() -> None:
    custom_after = (os.environ.get("CUSTOM_AFTER") or "").strip()
    custom_before = (os.environ.get("CUSTOM_BEFORE") or "").strip()
    if custom_after and custom_before:
        after_ts = int(datetime.strptime(custom_after, "%Y-%m-%d %H:%M").replace(tzinfo=JST).timestamp())
        before_ts = int(datetime.strptime(custom_before, "%Y-%m-%d %H:%M").replace(tzinfo=JST).timestamp())
    else:
        now = datetime.now(JST)
        before_ts = int(now.timestamp())
        after_ts = int((now - timedelta(hours=6)).timestamp())

    print(f"[diag] 比較窓: {datetime.fromtimestamp(after_ts, JST)} 〜 {datetime.fromtimestamp(before_ts, JST)}", flush=True)

    slack = SlackTools()

    # ---- 新方式 ----
    joined = slack.list_joined_channels()
    target_channels = [
        ch for ch in joined
        if ("社内" in ch["name"] or "社外" in ch["name"])
        and not any(bad in ch["name"] for bad in ["mdx_", "dxm_", "hajimari"])
    ]
    joined_names = {ch["name"] for ch in joined}
    print(f"[diag][new] bot参加ch: {len(joined)}件（対象: {len(target_channels)}件）", flush=True)

    new_raw = poll_and_match(slack, target_channels, KEYWORD_GROUPS, after_ts, before_ts)
    new_threads = filter_and_dedupe(new_raw)
    print(f"[diag][new] raw={len(new_raw)} → dedup後={len(new_threads)} threads", flush=True)

    # ---- 旧方式 ----
    old_raw = search_all_groups(slack, KEYWORD_GROUPS, after_ts, before_ts)
    old_threads = filter_and_dedupe(old_raw)
    print(f"[diag][old] raw={len(old_raw)} → dedup後={len(old_threads)} threads", flush=True)

    # ---- 差分 ----
    new_keys = {(t["channel_id"], t["thread_ts"]) for t in new_threads}
    old_only = [t for t in old_threads if (t["channel_id"], t["thread_ts"]) not in new_keys]

    print(f"\n[diag] === 旧方式だけが見つけた・新方式が見逃したスレッド: {len(old_only)}件 ===", flush=True)
    for t in old_only:
        ch_name = t["channel_name"]
        bot_in_channel = ch_name in joined_names
        print(
            f"  - ch={ch_name!r} bot参加={'○' if bot_in_channel else '×（招待漏れ）'} "
            f"keyword={t.get('matched_keyword')!r} permalink={t.get('permalink')}",
            flush=True,
        )

    if old_only:
        missing_bot = sum(1 for t in old_only if t["channel_name"] not in joined_names)
        print(
            f"\n[diag] 見逃し{len(old_only)}件のうち、bot未参加chが原因: {missing_bot}件 / "
            f"bot参加済みなのに新方式で拾えなかった: {len(old_only) - missing_bot}件",
            flush=True,
        )


if __name__ == "__main__":
    main()
