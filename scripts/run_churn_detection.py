"""
解約リスク検知くん - GitHub Actions本体
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.detector import DetectorConfig, run_detection

CONFIG = DetectorConfig(
    name="解約リスク検知くん",
    detection_type="解約リスク",
    notification_channel="C0APPHC8UR5",
    skill_path=Path(__file__).parent.parent / "skills" / "churn-detection-realtime.md",
    legacy_header_patterns=[
        "Slack - 解約リスク検知くん",
        "解約リスク検知くん リアルタイム",
    ],
    keyword_groups={
        "A": ["解約", "契約終了", "更新しない", "継続しない", "発注終了",
              "終了見込み", "終了予定", "継続が難しい", "継続を検討",
              "次回更新しない", "発注停止", "発注見合わせ", "発注保留",
              "発注できない", "発注が難しい"],
        "B": ["予算削減", "コスト削減", "予算見直し", "費用", "内製化",
              "予算を削減", "予算カット", "予算が厳しい", "予算オーバー",
              "コストカット"],
        "C": ["成果が見えない", "期待と違う", "品質懸念", "的はずれ",
              "リプレイス", "手応えがない", "成果が出ていない",
              "改善が見られない", "変化がない"],
        "D": ["契約見直し", "精査", "縮小", "撤退", "取引影響", "更新について",
              "来期以降", "来期の方針", "継続の判断", "担当変更"],
    },
)


if __name__ == "__main__":
    run_detection(CONFIG)
