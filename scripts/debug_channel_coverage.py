"""
診断専用（一時ファイル）: bot移行後の検知対象チャンネル漏れを調査する。
Claude / Sheets / OAuth には一切触らない。SLACK_BOT_TOKEN のみ使用。
原因特定後は削除すること。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from lib.slack_tools import SlackTools

BAD = ["mdx_", "dxm_", "hajimari"]


def main() -> None:
    slack = SlackTools()
    all_channels = slack.list_all_visible_channels()

    def is_target(name: str) -> bool:
        return ("社内" in name or "社外" in name) and not any(b in name for b in BAD)

    targets = [ch for ch in all_channels if is_target(ch["name"])]
    joined_targets = [ch for ch in targets if ch["is_member"]]
    missing_targets = [ch for ch in targets if not ch["is_member"]]

    print(f"[coverage] 全可視チャンネル数: {len(all_channels)}", flush=True)
    print(f"[coverage] 社内/社外対象チャンネル数: {len(targets)}", flush=True)
    print(f"[coverage] bot在室（検知対象に入っている）: {len(joined_targets)}", flush=True)
    print(f"[coverage] bot未在室（検知漏れ・public channelのみ判定可）: {len(missing_targets)}", flush=True)
    if missing_targets:
        print("[coverage] 漏れch一覧:", flush=True)
        for ch in missing_targets:
            print(f"  - {ch['name']} ({ch['id']})", flush=True)


if __name__ == "__main__":
    main()
