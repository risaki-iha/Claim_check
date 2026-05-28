r"""
SupervisorResolver スモークテスト（実スプシの代表行をモックして実行）

実行: py scripts\smoke_test_supervisor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.supervisor_map import SupervisorResolver


# 実スプシの代表行を再現（A〜G列まで＝7列以上必要）。
# 行1〜3はヘッダー扱いでスキップされる。データは行4(idx 3)から。
MOCK_ROWS = [
    # row 1: 優先度行（スキップ対象）
    ["", "優先度：", "2", "4", "3", "4", "3", "3"],
    # row 2: 注釈行（スキップ対象）
    ["", "【公開用】案件ごとAM一覧", "↓クライアント名から", "↓手入力", "", "", "↓コール名検索から", "↓コール名検索から"],
    # row 3: ヘッダー行（スキップ対象）
    ["", "コール名検索", "コール名検索 ※B列以外にある場合手入力", "slackメンション先 ※マネ", "MGメアド", "slackチャンネル名", "slackチャンネルID", "クライアント名"],

    # row 4以降: データ行
    # 三木テスト枠（カバヤ＝channel_id あり）
    ["", "カバヤ食品", "", "三木美羽", "miu_miki@nyle.co.jp", "社内_カバヤ食品_100758-001", "C09PM52KCP4", "カバヤ食品株式会社"],
    # 三木テスト枠（ジェイボックス＝channel_id 空、コール名のみ）
    ["", "ジェイボックス", "", "三木美羽", "miu_miki@nyle.co.jp", "", "", "株式会社ジェイボックス"],
    # 古市テスト枠
    ["", "オリックス", "", "古市朱里", "shuri_fr@nyle.co.jp", "社内_オリックス_100100-001", "C0XXX_FURUICHI", "オリックス株式会社"],
    # 伊波テスト枠
    ["", "ダイブ", "", "伊波利咲", "risaki_iha@nyle.co.jp", "社内_ダイブ_100719-001", "C09MCNAQ0CQ", "株式会社ダイブ"],
    # email 空・name のみ（フォールバック検証用）
    ["", "サンプル名前のみ", "", "テスト太郎", "", "社内_サンプル_999-001", "C_NAME_ONLY", "サンプル株式会社"],
    # 短い行（スキップ）
    ["", "短い行", "", "誰か", "x@nyle.co.jp"],
]

# Slack users.list のモック
USER_ID_BY_EMAIL = {
    "miu_miki@nyle.co.jp": "U_MIKI",
    "shuri_fr@nyle.co.jp": "U_FURUICHI",
    "risaki_iha@nyle.co.jp": "U_IHA",
}
USER_ID_BY_NAME = {
    "テスト太郎": "U_TEST_TARO",
}


def run() -> int:
    r = SupervisorResolver()
    r.load_from_rows(MOCK_ROWS)

    failures: list[str] = []

    def check(label: str, got, expected):
        if got != expected:
            failures.append(f"  ❌ {label}: expected={expected!r} got={got!r}")
        else:
            print(f"  ✓ {label}")

    print("=== resolve_entry ===")
    check(
        "channel_id 完全マッチ（カバヤ）",
        r.resolve_entry("C09PM52KCP4", "any"),
        {"name": "三木美羽", "email": "miu_miki@nyle.co.jp"},
    )
    check(
        "コール名部分マッチ（ジェイボックス）",
        r.resolve_entry("", "社内_ジェイボックス_100063-001"),
        {"name": "三木美羽", "email": "miu_miki@nyle.co.jp"},
    )
    check(
        "未マッチ → None",
        r.resolve_entry("C_UNKNOWN", "社内_存在しない_999"),
        None,
    )

    print("\n=== resolve_mention（メアド経由） ===")
    check(
        "三木（channel_id マッチ → email 解決）",
        r.resolve_mention("C09PM52KCP4", "any", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_MIKI>",
    )
    check(
        "古市（channel_id マッチ → email 解決）",
        r.resolve_mention("C0XXX_FURUICHI", "any", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_FURUICHI>",
    )
    check(
        "伊波（channel_id マッチ → email 解決）",
        r.resolve_mention("C09MCNAQ0CQ", "any", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_IHA>",
    )

    print("\n=== resolve_mention（コール名フォールバック） ===")
    check(
        "三木（コール名マッチ → email 解決）",
        r.resolve_mention("", "社内_ジェイボックス_100063-001", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_MIKI>",
    )

    print("\n=== resolve_mention（名前フォールバック） ===")
    check(
        "メアド空 → 名前で解決",
        r.resolve_mention("C_NAME_ONLY", "any", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_TEST_TARO>",
    )

    print("\n=== resolve_mention（解決不能） ===")
    check(
        "未マッチ → None（マネージャー行を出さない）",
        r.resolve_mention("C_UNKNOWN", "社内_存在しない_999", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        None,
    )
    check(
        "マッチするがユーザ辞書に該当なし → None",
        r.resolve_mention("C_NAME_ONLY", "any", {}, {}),
        None,
    )

    print()
    if failures:
        print("=== 失敗あり ===")
        for f in failures:
            print(f)
        return 1
    print("=== 全テスト通過 ===")
    return 0


if __name__ == "__main__":
    sys.exit(run())
