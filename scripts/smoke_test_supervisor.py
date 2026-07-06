r"""
SupervisorResolver スモークテスト（実スプシの代表行をモックして実行）

実行: py scripts\smoke_test_supervisor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.supervisor_map import SupervisorResolver


# 実スプシの代表行を再現。実際のシート構造（2026-07 確認）に合わせた列配置。
# A(0) B(1)コール名検索 C(2)コール名検索サブ D(3)顧客名 E(4)顧客窓口名 F(5)顧客窓口No
# G(6)AM H(7)マネ I(8)MGメアド J(9)Slackチャンネル名 K(10)SlackチャンネルID
# 行1〜4(idx 0〜3)はヘッダー扱いでスキップ。データは行5(idx 4)から。
MOCK_ROWS = [
    # row 1〜4: スキップ対象（実スプシの注釈・ヘッダー行）
    ["", "※ARRAYFORMULA関数で管理中"],
    ["", "データ元：「2_紐づけ一覧」シート"],
    ["", "空白セルはスプシ側で更新"],
    ["", "コール名検索", "コール名検索（サブ）", "顧客名", "顧客窓口名", "顧客窓口No", "AM", "マネ", "MGメアド", "Slackチャンネル名", "SlackチャンネルID"],

    # row 5以降: データ行
    #    A   B                C   D                       E    F              G   H            I                        J                                       K
    # ①channel_id マッチ用
    ["", "カバヤ食品",       "", "カバヤ食品株式会社",     "", "100758-001",  "", "三木美羽",  "miu_miki@nyle.co.jp",   "社内_カバヤ食品_100758-001",           "C09PM52KCP4"],
    ["", "オリックス",       "", "オリックス株式会社",     "", "100100-001",  "", "古市朱里",  "shuri_fr@nyle.co.jp",   "社内_オリックス_100100-001",           "C0XXX_FURUICHI"],
    ["", "ダイブ",           "", "株式会社ダイブ",          "", "100719-001",  "", "伊波利咲",  "risaki_iha@nyle.co.jp", "社内_ダイブ_100719-001",               "C09MCNAQ0CQ"],
    # ②顧客NO マッチ用（channel_id 空＝①をスキップして②へ）
    # 楽天: ch末尾枝番(-003) と F列枝番(-004) がズレる → 6桁本体100093で解決
    ["", "楽天",             "", "楽天グループ株式会社",   "", "100093-004",  "", "板津直前",  "naosaki_it@nyle.co.jp", "社内_楽天-gora-ゴルフ事業_100093-003", ""],
    # プライムクロス: ch名に枝番なし(100706) / F列=100706-002 → 6桁本体で解決
    ["", "プライムクロス",   "", "株式会社プライムクロス", "", "100706-002",  "", "小野寺雄大", "yudai_onodera@nyle.co.jp","社内_プライムクロス_100706",          ""],
    # 旭化成: NOがch名の途中 → 最後の6桁=100414で解決
    ["", "旭化成ホームズ",   "", "旭化成ホームズ株式会社", "", "100414-001",  "", "板津直前",  "naosaki_it@nyle.co.jp", "社内_旭化成ホームズ_100414-001_旧-旭化成不動産レジデンス", ""],
    # ③顧客名マッチ用（channel_id 空 & 顧客NO 無し）
    ["", "ジェイボックス",   "", "株式会社ジェイボックス", "", "",            "", "三木美羽",  "miu_miki@nyle.co.jp",   "",                                     ""],
    # email 空・name のみ（フォールバック検証用）
    ["", "サンプル名前のみ", "", "サンプル株式会社",        "", "",            "", "テスト太郎", "",                     "社内_サンプル_999-001",                "C_NAME_ONLY"],
    # 短い行（スキップ）
    ["", "短い行", "", "誰か", "x@nyle.co.jp"],
]

# Slack users.list のモック
USER_ID_BY_EMAIL = {
    "miu_miki@nyle.co.jp": "U_MIKI",
    "shuri_fr@nyle.co.jp": "U_FURUICHI",
    "risaki_iha@nyle.co.jp": "U_IHA",
    "naosaki_it@nyle.co.jp": "U_ITAZU",
    "yudai_onodera@nyle.co.jp": "U_ONODERA",
    "toru_my@nyle.co.jp": "U_MIYAZAWA",  # DEFAULT_MENTION_EMAIL（宮澤）
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

    print("=== ① channel_id 完全マッチ ===")
    check(
        "カバヤ（channel_id マッチ）",
        r.resolve_entry("C09PM52KCP4", "any"),
        {"name": "三木美羽", "email": "miu_miki@nyle.co.jp"},
    )

    print("\n=== ② 顧客NO 6桁本体マッチ ===")
    check(
        "楽天: ch枝番-003 と F列枝番-004 がズレても6桁本体100093で解決",
        r.resolve_entry("", "社内_楽天-gora-ゴルフ事業_100093-003"),
        {"name": "板津直前", "email": "naosaki_it@nyle.co.jp"},
    )
    check(
        "プライムクロス: ch名に枝番なし(100706)でも6桁本体で解決",
        r.resolve_entry("", "社内_プライムクロス_100706"),
        {"name": "小野寺雄大", "email": "yudai_onodera@nyle.co.jp"},
    )
    check(
        "旭化成: NOがch名の途中でも最後の6桁100414で解決",
        r.resolve_entry("", "社内_旭化成ホームズ_100414-001_旧-旭化成不動産レジデンス"),
        {"name": "板津直前", "email": "naosaki_it@nyle.co.jp"},
    )
    check(
        "未登録の6桁(888888) → ②でマッチしない",
        r.resolve_entry("", "社内_未登録案件_888888"),
        None,
    )

    print("\n=== ③ 顧客名セグメントマッチ ===")
    check(
        "ジェイボックス（顧客NO無し → 顧客名マッチ）",
        r.resolve_entry("", "社内_ジェイボックス_新規案件"),
        {"name": "三木美羽", "email": "miu_miki@nyle.co.jp"},
    )
    check(
        "未マッチ → None",
        r.resolve_entry("C_UNKNOWN", "社内_存在しない_999"),
        None,
    )

    print("\n=== resolve_mention（① channel_id → email 解決） ===")
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

    print("\n=== resolve_mention（② 顧客NO マッチ → email 解決） ===")
    check(
        "楽天（顧客NO 6桁本体マッチ → email 解決）",
        r.resolve_mention("", "社内_楽天-gora-ゴルフ事業_100093-003", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_ITAZU>",
    )

    print("\n=== resolve_mention（③ 顧客名マッチ → email 解決） ===")
    check(
        "三木（顧客名マッチ → email 解決）",
        r.resolve_mention("", "社内_ジェイボックス_新規案件", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_MIKI>",
    )

    print("\n=== resolve_mention（名前フォールバック） ===")
    check(
        "メアド空 → 名前で解決",
        r.resolve_mention("C_NAME_ONLY", "any", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_TEST_TARO>",
    )

    print("\n=== resolve_mention（解決不能・default_email なし） ===")
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

    print("\n=== resolve_mention（宮澤フォールバック・default_email あり） ===")
    DEFAULT = "toru_my@nyle.co.jp"
    check(
        "一覧外 → 宮澤にフォールバック",
        r.resolve_mention(
            "C_UNKNOWN", "社内_存在しない_999", USER_ID_BY_NAME, USER_ID_BY_EMAIL, default_email=DEFAULT
        ),
        "<@U_MIYAZAWA>",
    )
    check(
        "一覧にはいるが user_id 引けない → 宮澤にフォールバック",
        r.resolve_mention(
            "C09PM52KCP4", "any", {}, {"toru_my@nyle.co.jp": "U_MIYAZAWA"}, default_email=DEFAULT
        ),
        "<@U_MIYAZAWA>",
    )
    check(
        "一覧で解決できれば宮澤に流れない（既存メンション優先）",
        r.resolve_mention(
            "C09PM52KCP4", "any", USER_ID_BY_NAME, USER_ID_BY_EMAIL, default_email=DEFAULT
        ),
        "<@U_MIKI>",
    )
    check(
        "宮澤すらユーザ辞書にない → None",
        r.resolve_mention("C_UNKNOWN", "社内_存在しない_999", {}, {}, default_email=DEFAULT),
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
