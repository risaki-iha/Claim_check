"""
クレーム検知くん - GitHub Actions本体
"""

import sys
from pathlib import Path

# scripts/lib をインポート可能に
sys.path.insert(0, str(Path(__file__).parent))

from lib.detector import DetectorConfig, run_detection

CONFIG = DetectorConfig(
    name="クレーム検知くん",
    detection_type="クレーム",
    notification_channel="C0ABRS7NR27",
    skill_path=Path(__file__).parent.parent / "skills" / "claim-detection-realtime.md",
    legacy_header_patterns=[
        "Slack - クレーム検知くん",
        "クレーム検知くん リアルタイム",
    ],
    keyword_groups={
        "A": ["クレーム", "謝罪", "申し訳", "ご迷惑", "不信感", "不満",
              "先方からFB", "先方からフィードバック", "早急に改善", "改善必要な状況", "急遽MTG"],
        "B": ["ミス", "遅延", "指摘", "不備", "問題", "確認不足", "対応漏れ",
              "対応遅れ", "連携漏れ", "連携遅れ", "締め切り", "捺印", "検収ズレ",
              "気づかず", "催促", "返事がない", "返答がない", "返答待ち",
              "チェックバックが遅い", "返信がこない", "連絡がつかない", "連絡が取れない",
              "担当者不在", "担当者が変わった", "期日間違え", "セルがズレ",
              "数値が違う", "計算が違う", "金額が違う", "急すぎ", "納期が短い",
              "着手していない", "対応できません", "リソースが足りない"],
        "C": ["解約", "契約見直し", "予算削減", "費用", "納期", "間に合わ"],
        "D": ["品質", "クオリティ", "齟齬", "懸念", "認識違い", "改善",
              "イマイチ", "やりにくい", "ズレている", "方針が変わった",
              "認識が合っていない", "すり合わせ"],
        "E": ["インデックス", "アクセスできない", "閲覧できない", "移管",
              "障害", "エラー"],
    },
)


if __name__ == "__main__":
    run_detection(CONFIG)
