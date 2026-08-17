"""
【診断専用・実害なし】見逃した候補スレッドの実際のメッセージ本文を表示する。
「重要な内容か」「既に通知済みスレッドの続きか」を判断するための材料集め。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.slack_tools import SlackTools
from lib.sheets_tools import SheetsTools

# (channel_id, thread_ts, matched_message_ts) の組。diag_compare_search_methods.py の出力から抜粋
TARGETS = [
    ("C0B85UVAGDN", "1786945996.890919", "1786946032.620169"),  # screenアドバンスト
    ("C0AJJCAM6P3", "1786945220.794029", "1786945428.132629"),  # セブン銀行
    ("C075GRTP2QM", "1786680645.695969", "1786945151.170819"),  # sbi損害保険(申し訳)
    ("C08JZ7QC4M6", "1785915722.325949", "1786932303.670069"),  # ユーエスイー(1)
    ("C0ARJH50F5W", "1784074587.409199", "1786927576.922109"),  # エヌデーソフトウェア
    ("C0966R5E0BB", "1785831427.105289", "1786945722.858479"),  # 日本ビジネスシステムズ
    ("C0BJ2UMAH2Q", "1786070832.534609", "1786931923.728579"),  # udトラックス
    ("C0B3SNW6VC0", "1780385443.945979", "1786937549.544719"),  # dgbt様
    ("C0BCA361U6P", None, "1786933304.121539"),                  # 日立システムズ(トップレベル)
    ("C0ASLAJ4N05", "1784797281.026829", "1786946241.907859"),  # nttdocomo-カーシェア
    ("C08C23DTPEF", "1786513326.000419", "1786935340.811589"),  # アデコ
]


def main() -> None:
    slack = SlackTools()
    sheets = SheetsTools()

    notified_keys = sheets.get_notified_thread_keys()

    for ch_id, thread_ts, msg_ts in TARGETS:
        print(f"\n=== ch={ch_id} thread_ts={thread_ts} ===", flush=True)
        already_notified = (ch_id, thread_ts) in notified_keys if thread_ts else False
        print(f"[過去に通知済みスレッドか] {'YES（既知）' if already_notified else 'NO（未通知＝今回が初見）'}", flush=True)

        if thread_ts:
            replies = slack.read_thread(ch_id, thread_ts)
            target = next((r for r in replies if r.get("ts") == msg_ts), None)
        else:
            recent = slack.read_channel_recent(ch_id, limit=50)
            target = next((r for r in recent if r.get("ts") == msg_ts), None)

        if target:
            text = target.get("text", "")
            print(f"[本文] {text[:200]}", flush=True)
        else:
            print("[本文] 取得できず（メッセージが見つからない）", flush=True)


if __name__ == "__main__":
    main()
