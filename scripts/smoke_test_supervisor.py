r"""
SupervisorResolver スモークテスト（実スプシの代表行をモックして実行）

実行: py scripts\smoke_test_supervisor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.supervisor_map import SupervisorResolver


# 実スプシの代表行を再現（A〜J列＝10列。J列＝顧客窓口No）。
# 行1〜3はヘッダー扱いでスキップされる。データは行4(idx 3)から。
# 列: A0 B1(コール名) C2 D3(マネ名) E4(メアド) F5(ch名) G6(chID) H7(クライアント名) I8(窓口名) J9(顧客窓口No)
MOCK_ROWS = [
    # row 1: 優先度行（スキップ対象）
    ["", "優先度：", "2", "4", "3", "4", "3", "3"],
    # row 2: 注釈行（スキップ対象）
    ["", "【公開用】案件ごとAM一覧", "↓クライアント名から", "↓手入力", "", "", "↓コール名検索から", "↓コール名検索から"],
    # row 3: ヘッダー行（スキップ対象）
    ["", "コール名検索", "コール名検索 ※B列以外にある場合手入力", "slackメンション先 ※マネ", "MGメアド", "slackチャンネル名", "slackチャンネルID", "クライアント名", "窓口名", "顧客窓口No"],

    # row 4以降: データ行
    # 三木テスト枠（カバヤ＝channel_id あり）
    ["", "カバヤ食品", "", "三木美羽", "miu_miki@nyle.co.jp", "社内_カバヤ食品_100758-001", "C09PM52KCP4", "カバヤ食品株式会社", "-", "100758-001"],
    # 三木テスト枠（ジェイボックス＝channel_id 空・顧客No 無し・コール名のみ＝③コール名フォールバック検証用）
    ["", "ジェイボックス", "", "三木美羽", "miu_miki@nyle.co.jp", "", "", "株式会社ジェイボックス"],
    # 古市テスト枠
    ["", "オリックス", "", "古市朱里", "shuri_fr@nyle.co.jp", "社内_オリックス_100100-001", "C0XXX_FURUICHI", "オリックス株式会社", "-", "100100-001"],
    # 伊波テスト枠
    ["", "ダイブ", "", "伊波利咲", "risaki_iha@nyle.co.jp", "社内_ダイブ_100719-001", "C09MCNAQ0CQ", "株式会社ダイブ", "-", "100719-001"],
    # 楽天: チャンネル末尾の枝番(-003)と J列の枝番(-004)がズレる → 6桁本体100093で解決（channel_idはあえて空にして②を強制）
    ["", "楽天", "", "板津直前", "naosaki_it@nyle.co.jp", "社内_楽天-gora-ゴルフ事業_100093-003", "", "楽天グループ株式会社", "法人サービス", "100093-004"],
    # プライムクロス: チャンネル名に枝番なし(100706) / J=100706-002 → 6桁本体で解決
    ["", "プライムクロス", "", "小野寺雄大", "yudai_onodera@nyle.co.jp", "社内_プライムクロス_100706", "", "株式会社プライムクロス", "野村不動産 KURASUMA", "100706-002"],
    # 旭化成: NOがチャンネル名の途中(_100414-001_旧-…) → 最後の6桁=100414で解決
    ["", "旭化成ホームズ", "", "板津直前", "naosaki_it@nyle.co.jp", "社内_旭化成ホームズ_100414-001_旧-旭化成不動産レジデンス", "", "旭化成ホームズ株式会社", "-", "100414-001"],
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
    "naosaki_it@nyle.co.jp": "U_ITAZU",       # 楽天・旭化成（板津）
    "yudai_onodera@nyle.co.jp": "U_ONODERA",  # プライムクロス
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

    print("=== resolve_entry（① channel_id） ===")
    check(
        "channel_id 完全マッチ（カバヤ）",
        r.resolve_entry("C09PM52KCP4", "any"),
        {"name": "三木美羽", "email": "miu_miki@nyle.co.jp"},
    )

    print("\n=== resolve_entry（② 顧客NO 6桁本体マッチ） ===")
    check(
        "楽天: チャンネル枝番-003 と J列枝番-004 がズレても6桁本体100093で解決",
        r.resolve_entry("", "社内_楽天-gora-ゴルフ事業_100093-003"),
        {"name": "板津直前", "email": "naosaki_it@nyle.co.jp"},
    )
    check(
        "プライムクロス: チャンネル名に枝番なし(100706)でも6桁本体で解決",
        r.resolve_entry("", "社内_プライムクロス_100706"),
        {"name": "小野寺雄大", "email": "yudai_onodera@nyle.co.jp"},
    )
    check(
        "旭化成: NOがチャンネル名の途中(_100414-001_旧-…)でも最後の6桁で解決",
        r.resolve_entry("", "社内_旭化成ホームズ_100414-001_旧-旭化成不動産レジデンス"),
        {"name": "板津直前", "email": "naosaki_it@nyle.co.jp"},
    )
    check(
        "顧客NOマッチはクライアント名に依存しない（名前が違っても6桁一致で解決）",
        r.resolve_entry("", "社内_全然ちがう名前_100093-001"),
        {"name": "板津直前", "email": "naosaki_it@nyle.co.jp"},
    )
    check(
        "未登録の6桁(888888) → ②でマッチしない → None",
        r.resolve_entry("", "社内_未登録案件_888888"),
        None,
    )

    print("\n=== resolve_entry（③ コール名フォールバック） ===")
    check(
        "顧客No無しチャンネルはコール名部分マッチで解決（ジェイボックス）",
        r.resolve_entry("", "社内_ジェイボックス_新規案件"),
        {"name": "三木美羽", "email": "miu_miki@nyle.co.jp"},
    )
    check(
        "未マッチ（NOもコール名も無し） → None",
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

    print("\n=== resolve_mention（顧客NOマッチ → email 解決） ===")
    check(
        "楽天（顧客NO 6桁本体マッチ → email 解決）",
        r.resolve_mention("", "社内_楽天-gora-ゴルフ事業_100093-003", USER_ID_BY_NAME, USER_ID_BY_EMAIL),
        "<@U_ITAZU>",
    )

    print("\n=== resolve_mention（コール名フォールバック） ===")
    check(
        "三木（コール名マッチ → email 解決）",
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
