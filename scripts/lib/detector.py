"""
検知本体ロジック（クレーム検知くん／解約リスク検知くん 共通）

設計方針:
- skill .md の中身は変更しない（精度維持のため）
- AI 判定は Claude に skill 内容を渡して任せる
- Slack 検索／スレッド取得／通知送信／スプシ書き込みは Python が担当
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .claude_oauth import ClaudeClient
from .slack_tools import SlackTools
from .sheets_tools import SheetsTools
from .supervisor_map import SupervisorResolver, DEFAULT_MENTION_EMAIL

JST = timezone(timedelta(hours=9))
JP_WEEKDAYS = "月火水木金土日"

# 検知対象から除外する投稿者の Slack user_id
# - 議事録転送bot（自動投稿された議事録はリアルタイム検知の対象外）
EXCLUDED_AUTHOR_USER_IDS = {
    "U0B305165M1",  # 議事録転送bot
}


@dataclass
class DetectorConfig:
    name: str  # "クレーム検知くん" / "解約リスク検知くん"
    detection_type: str  # スプシの「検知内容」列に入る値
    notification_channel: str  # 通知先チャンネルID
    keyword_groups: dict  # { "A": [...], "B": [...] }
    skill_path: Path
    legacy_header_patterns: list  # 過去通知ヘッダーの正規表現
    notification_username: str = ""  # Slack投稿時の表示名（空ならBotデフォルト名）。chat:write.customize スコープ必須
    header_emoji: str = "⚡"  # ヘッダー先頭の絵文字


def run_detection(config: DetectorConfig) -> None:
    # 営業時間外（JST 10:00 未満 or 21:00 以上）のスケジュール実行はスキップ
    # GitHub Actions の cron 遅延で深夜に動くのを防ぐ。手動実行は対象外。
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    now_jst = datetime.now(JST)
    if event == "schedule" and (now_jst.hour < 10 or now_jst.hour >= 21):
        print(
            f"[skip] 営業時間外 ({now_jst.strftime('%H:%M')} JST) のためスキップ。"
            f"次の営業時間の cron が前回通知から続きを検索する。",
            flush=True,
        )
        return

    claude = ClaudeClient()
    try:
        slack = SlackTools()
        sheets = SheetsTools()
        skill_content = config.skill_path.read_text(encoding="utf-8")

        # 1. 検索範囲決定
        after_ts, before_ts = determine_search_range(slack, config)
        print(
            f"[range] {fmt_ts(after_ts)} 〜 {fmt_ts(before_ts)}",
            flush=True,
        )

        # 2. キーワード検索
        candidates = search_all_groups(slack, config.keyword_groups, after_ts, before_ts)
        print(f"[search] {len(candidates)} hits", flush=True)

        # 3. チャンネルフィルター + デデュプ
        threads = filter_and_dedupe(candidates)
        print(f"[filter] {len(threads)} threads after filter", flush=True)

        # 4. スレッド取得 + ユーザープロフィール
        enriched = enrich_threads(slack, threads)
        print(f"[enrich] {len(enriched)} threads enriched", flush=True)

        # 5. AI 判定
        if enriched:
            results = evaluate_with_claude(claude, enriched, skill_content, config)
        else:
            results = []
        print(f"[evaluate] {len(results)} detections after AI", flush=True)

        # 5.5 同一スレッド内で複数論点が出た場合は1件に集約
        results = merge_results_by_thread(results)
        print(f"[merge] {len(results)} detections after thread merge", flush=True)

        # 6. Slack 通知送信（検知0件の時はスキップして通知ノイズを減らす）
        if results:
            # 上長メンション解決の準備（失敗時は【マネージャー】行を出さない）
            resolver = SupervisorResolver()
            try:
                resolver.load()
            except Exception as e:
                print(
                    f"[supervisor] マスタスプシ読込失敗、メンション行は出さずに継続: "
                    f"{type(e).__name__}: {e!r}",
                    flush=True,
                )
                resolver = None

            user_maps = slack.list_users() if resolver else {"by_name": {}, "by_email": {}}

            notification_text = build_notification_text(
                config, results, after_ts, before_ts, resolver, user_maps
            )
            slack.post_message(
                config.notification_channel,
                notification_text,
                username=config.notification_username,
            )
            print("[notify] posted", flush=True)

            # 7. スプシ書き込み
            rows = build_sheet_rows(results, config)
            appended = sheets.append_rows(rows)
            print(f"[sheets] appended {appended} rows", flush=True)
        else:
            print("[notify] 検知0件のため通知スキップ", flush=True)
    finally:
        # ローテーションが**実際に起きた場合だけ** GITHUB_OUTPUT に書き出す。
        # OAuth refresh が失敗した場合（invalid_grant 等）に古いトークンを
        # 書き戻して並行ジョブの成功結果を破壊するのを防ぐ。
        if claude.has_token_rotated():
            _emit_refresh_token_output(claude.get_current_refresh_token())
        else:
            print("[oauth] ローテ未発生のため GITHUB_OUTPUT 書き出しスキップ", flush=True)


def _emit_refresh_token_output(token: str) -> None:
    """OAuthローテ済みの最新 refresh_token を GITHUB_OUTPUT に書き出す。"""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return  # ローカル実行時はスキップ
    # ログに値が出ないようマスク登録
    print(f"::add-mask::{token}", flush=True)
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"new_refresh_token={token}\n")
    print("[oauth] 🔁 GITHUB_OUTPUT に new_refresh_token を書き出した", flush=True)


# ---------- 検索範囲 ----------

def determine_search_range(slack: SlackTools, config: DetectorConfig) -> tuple[int, int]:
    """前回通知メッセージの終了時刻を抽出して after に設定"""
    import os
    # 手動指定があればそれを優先（JST文字列 "YYYY-MM-DD HH:MM"）
    custom_after = (os.environ.get("CUSTOM_AFTER") or "").strip()
    custom_before = (os.environ.get("CUSTOM_BEFORE") or "").strip()
    if custom_after and custom_before:
        af = int(datetime.strptime(custom_after, "%Y-%m-%d %H:%M").replace(tzinfo=JST).timestamp())
        bf = int(datetime.strptime(custom_before, "%Y-%m-%d %H:%M").replace(tzinfo=JST).timestamp())
        return af, bf

    now_ts = int(datetime.now(JST).timestamp())
    messages = slack.read_channel_recent(config.notification_channel, limit=30)

    last_end = None
    for msg in messages:
        text = msg.get("text", "")
        if any(p in text for p in config.legacy_header_patterns) or any(
            re.search(rgx, text) for rgx in [
                r"検知期間：(\d{4}/\d{1,2}/\d{1,2})",
            ]
        ):
            last_end = parse_end_time_from_header(text)
            if last_end:
                break

    if last_end:
        return last_end, now_ts

    # フォールバック: 実行時刻に応じて範囲を設定
    now_jst = datetime.now(JST)
    if now_jst.hour < 11:
        # 朝10時の実行 → 前日20:00 〜 当日10:00
        start = now_jst.replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(hours=14)
    else:
        # 11時以降 → 直近1時間
        start = now_jst - timedelta(hours=1)
    return int(start.timestamp()), now_ts


def parse_end_time_from_header(text: str) -> int | None:
    """通知のヘッダー部から終了時刻を抽出"""
    # 新形式（同日内）: 「検知期間：2026/04/28（火） 12:00〜14:00」
    m = re.search(
        r"検知期間：(\d{4})/(\d{1,2})/(\d{1,2})（.）\s*(\d{1,2}):(\d{2})〜(\d{1,2}):(\d{2})",
        text,
    )
    if m:
        y, mo, d, _, _, eh, em = m.groups()
        dt = datetime(int(y), int(mo), int(d), int(eh), int(em), tzinfo=JST)
        return int(dt.timestamp())

    # 新形式（日またぎ）: 「検知期間：2026/04/24（金） 20:00〜2026/04/27（月） 10:00」
    m = re.search(
        r"検知期間：\d{4}/\d{1,2}/\d{1,2}（.）\s*\d{1,2}:\d{2}〜(\d{4})/(\d{1,2})/(\d{1,2})（.）\s*(\d{1,2}):(\d{2})",
        text,
    )
    if m:
        y, mo, d, eh, em = m.groups()
        dt = datetime(int(y), int(mo), int(d), int(eh), int(em), tzinfo=JST)
        return int(dt.timestamp())

    # 旧形式: 「— 2026/04/28 12:00〜14:00」
    m = re.search(
        r"—\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*\d{1,2}:\d{2}〜(\d{1,2}):(\d{2})", text
    )
    if m:
        y, mo, d, eh, em = m.groups()
        dt = datetime(int(y), int(mo), int(d), int(eh), int(em), tzinfo=JST)
        return int(dt.timestamp())

    return None


# ---------- 検索 ----------

def search_all_groups(
    slack: SlackTools, groups: dict, after_ts: int, before_ts: int
) -> list[dict]:
    results = []
    for group_name, keywords in groups.items():
        for kw in keywords:
            hits = slack.search(kw, after_ts, before_ts, limit=20)
            for h in hits:
                h["_keyword"] = kw
                h["_group"] = group_name
            results.extend(hits)
    return results


# ---------- フィルター + デデュプ ----------

def filter_and_dedupe(messages: list[dict]) -> list[dict]:
    """
    - チャンネル名に「社内」または「社外」を含むもののみ残す
    - thread_ts でデデュプ（一番古いものを採用）
    - mdx_, dxm_, hajimari は除外
    - EXCLUDED_AUTHOR_USER_IDS（議事録転送bot等）からの投稿は除外
    """
    seen = {}
    for m in messages:
        ch = m.get("channel", {})
        ch_name = ch.get("name", "") if isinstance(ch, dict) else ""
        if not ("社内" in ch_name or "社外" in ch_name):
            continue
        if any(bad in ch_name for bad in ["mdx_", "dxm_", "hajimari"]):
            continue

        # 議事録転送bot等、自動投稿系のメッセージは検知対象外
        author_id = m.get("user")
        if author_id in EXCLUDED_AUTHOR_USER_IDS:
            continue

        thread_ts = m.get("thread_ts") or m.get("ts")
        key = (ch.get("id"), thread_ts)
        if key not in seen:
            seen[key] = {
                "channel_id": ch.get("id"),
                "channel_name": ch_name,
                "thread_ts": thread_ts,
                "permalink": m.get("permalink"),
                "matched_keyword": m.get("_keyword"),
            }
    return list(seen.values())


# ---------- スレッド取得 + ユーザー情報 ----------

def enrich_threads(slack: SlackTools, threads: list[dict]) -> list[dict]:
    out = []
    for t in threads:
        msgs = slack.read_thread(t["channel_id"], t["thread_ts"])
        if not msgs:
            continue
        user_ids = {m.get("user") for m in msgs if m.get("user")}
        users = {uid: slack.read_user_profile(uid) for uid in user_ids}

        # 社内スタッフ（@nyle.co.jp）の display_name を投稿順に
        staff_seen = []
        for m in msgs:
            uid = m.get("user")
            if not uid:
                continue
            u = users.get(uid, {})
            if "@nyle.co.jp" in u.get("email", "") or "nyle.co.jp" in u.get("email", ""):
                name = u.get("name", "")
                if name and name not in staff_seen:
                    staff_seen.append(name)

        out.append(
            {
                **t,
                "messages": [
                    {
                        "ts": m.get("ts"),
                        "user_id": m.get("user"),
                        "user_name": users.get(m.get("user", ""), {}).get("name", ""),
                        "user_email": users.get(m.get("user", ""), {}).get("email", ""),
                        "text": m.get("text", ""),
                        "is_internal": "nyle.co.jp" in users.get(m.get("user", ""), {}).get("email", ""),
                    }
                    for m in msgs
                ],
                "staff_members": staff_seen,
            }
        )
    return out


# ---------- AI 判定 ----------

EVALUATE_BATCH_SIZE = 8


def evaluate_with_claude(
    claude: ClaudeClient, threads: list[dict], skill_content: str, config: DetectorConfig
) -> list[dict]:
    """
    skill 内容を system prompt に投入。threads を JSON で渡して構造化判定結果を受け取る。

    Claude Haiku の max_tokens=8K に収まるよう EVALUATE_BATCH_SIZE 件ずつ分割して評価する。
    1回でまとめて送ると出力が途中で切れて JSON パース失敗→0件扱いになる事故が起きるため。
    """
    all_results: list[dict] = []
    total_batches = (len(threads) + EVALUATE_BATCH_SIZE - 1) // EVALUATE_BATCH_SIZE
    for batch_idx in range(0, len(threads), EVALUATE_BATCH_SIZE):
        batch = threads[batch_idx : batch_idx + EVALUATE_BATCH_SIZE]
        batch_no = batch_idx // EVALUATE_BATCH_SIZE + 1
        results = _evaluate_batch(claude, batch, skill_content)
        print(
            f"[evaluate] batch {batch_no}/{total_batches}: {len(batch)} threads → {len(results)} hits",
            flush=True,
        )
        all_results.extend(results)
    return all_results


def _evaluate_batch(
    claude: ClaudeClient, threads: list[dict], skill_content: str
) -> list[dict]:
    user_input = json.dumps(
        {
            "task": "以下のスレッドを skill の手順 (Step 5) と重要度マトリクスに従って判定し、"
            "JSON配列のみを返してください（前後にテキストを付けない）。",
            "output_schema": [
                {
                    "channel_name": "string",
                    "channel_id": "string",
                    "thread_ts": "string",
                    "permalink": "string",
                    "importance": "🔴 即対応・上長報告 | 🟡 要対応・要確認 | 🔵 情報共有 | NOISE",
                    "summary": "1〜2行の概要",
                    "main_owner_name": "メインで対応している社内スタッフ名（無ければ空）",
                    "main_owner_email": "そのスタッフのメール",
                    "thread_summary": "スレッド全体の要点を3行程度",
                }
            ],
            "rules": [
                "ノイズ除外条件に該当するものは importance を 'NOISE' にする",
                "結果は JSON 配列のみ。コードブロックも不要",
            ],
            "threads": threads,
        },
        ensure_ascii=False,
    )

    resp = claude.messages_create(
        system=skill_content,
        messages=[{"role": "user", "content": user_input}],
        max_tokens=8000,
    )

    text = "".join(
        block.get("text", "")
        for block in resp.get("content", [])
        if block.get("type") == "text"
    ).strip()

    # コードブロックや前置きがあれば除去
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        results = json.loads(text)
    except json.JSONDecodeError:
        print(f"[evaluate] JSON parse failed. Raw output (head 500): {text[:500]}", flush=True)
        print(f"[evaluate] JSON parse failed. Raw output (tail 200): {text[-200:]}", flush=True)
        return []

    return [r for r in results if r.get("importance") and r.get("importance") != "NOISE"]


# ---------- 同スレ集約 ----------

_IMPORTANCE_RANK = {
    "🔴 即対応・上長報告": 3,
    "🟡 要対応・要確認": 2,
    "🔵 情報共有": 1,
}


def merge_results_by_thread(results: list[dict]) -> list[dict]:
    """
    同じ (channel_id, thread_ts) の検知は1件にマージする。
    - 重要度が最も高い件を代表に採用（permalink等もそれを使う）
    - 概要は各論点を箇条書きで結合
    - thread_ts が空の件はマージ対象外、そのまま残す
    """
    grouped: dict = {}
    no_thread: list[dict] = []
    for r in results:
        thread_ts = (r.get("thread_ts") or "").strip()
        if not thread_ts:
            no_thread.append(r)
            continue
        key = (r.get("channel_id", ""), thread_ts)
        grouped.setdefault(key, []).append(r)

    merged: list[dict] = []
    for items in grouped.values():
        if len(items) == 1:
            merged.append(items[0])
            continue
        items.sort(
            key=lambda x: _IMPORTANCE_RANK.get(x.get("importance", ""), 0),
            reverse=True,
        )
        rep = dict(items[0])
        summaries = [it.get("summary", "").strip() for it in items if it.get("summary")]
        if len(summaries) > 1:
            rep["summary"] = "\n".join(f"・{s}" for s in summaries)
        merged.append(rep)
    return merged + no_thread


# ---------- Slack 通知整形 ----------

def build_notification_text(
    config: DetectorConfig,
    results: list[dict],
    after_ts: int,
    before_ts: int,
    resolver: SupervisorResolver | None = None,
    user_maps: dict | None = None,
) -> str:
    period = format_period(after_ts, before_ts)
    # Slack の mrkdwn は *text* で太字（** ではなく * 1個）
    header = f"{config.header_emoji} *Slack - {config.name}* {config.header_emoji}\n検知期間：{period}"

    if not results:
        return f"{header}\n✅ 検知なし"

    by_importance = {"🔴 即対応・上長報告": [], "🟡 要対応・要確認": [], "🔵 情報共有": []}
    for r in results:
        imp = r.get("importance", "")
        if imp in by_importance:
            by_importance[imp].append(r)

    parts = [header]

    by_name = (user_maps or {}).get("by_name", {})
    by_email = (user_maps or {}).get("by_email", {})

    for label, items in by_importance.items():
        if not items:
            continue
        parts.append("")
        parts.append("")
        parts.append(f"*━━ {label} ({len(items)}件) ━━*")
        # 🔴 / 🟡 のみマネージャーをメンション。🔵 はノイズ抑制のため出さない。
        should_mention = label.startswith("🔴") or label.startswith("🟡")
        for i, r in enumerate(items):
            if i > 0:
                parts.append("")
                parts.append("─" * 20)
                parts.append("")
            else:
                parts.append("")
            staff = r.get("main_owner_name") or "-"
            parts.append(f"*{r.get('channel_name', '')}*")
            parts.append(f"【対応メンバー】{staff}")
            if should_mention and resolver is not None:
                mention = resolver.resolve_mention(
                    r.get("channel_id", ""),
                    r.get("channel_name", ""),
                    by_name,
                    by_email,
                    default_email=DEFAULT_MENTION_EMAIL,
                )
                if mention:
                    parts.append(f"【マネージャー】{mention}")
            parts.append("【概要】")
            parts.append(r.get("summary", ""))
            parts.append(f"🔗 <{r.get('permalink', '')}|スレッドを見る>")

    return "\n".join(parts)


def format_period(after_ts: int, before_ts: int) -> str:
    a = datetime.fromtimestamp(after_ts, tz=JST)
    b = datetime.fromtimestamp(before_ts, tz=JST)
    if a.date() == b.date():
        wd = JP_WEEKDAYS[a.weekday()]
        return f"{a.strftime('%Y/%m/%d')}（{wd}） {a.strftime('%H:%M')}〜{b.strftime('%H:%M')}"
    wda = JP_WEEKDAYS[a.weekday()]
    wdb = JP_WEEKDAYS[b.weekday()]
    return (
        f"{a.strftime('%Y/%m/%d')}（{wda}） {a.strftime('%H:%M')}〜"
        f"{b.strftime('%Y/%m/%d')}（{wdb}） {b.strftime('%H:%M')}"
    )


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=JST).strftime("%Y/%m/%d %H:%M")


# ---------- スプシ行構築 ----------

def build_sheet_rows(results: list[dict], config: DetectorConfig) -> list[dict]:
    rows = []
    for r in results:
        # 検知日時はスレッドが実発生した時刻（thread_ts = Slack Unix秒）を使う
        thread_ts_raw = r.get("thread_ts", "")
        try:
            detected_str = datetime.fromtimestamp(float(thread_ts_raw), tz=JST).strftime("%Y/%m/%d %H:%M")
        except (ValueError, TypeError):
            detected_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M")

        rows.append(
            {
                "検知媒体": "Slack",
                "検知内容": config.detection_type,
                "検知日時": detected_str,
                "チャンネル名": r.get("channel_name", ""),
                "重要度": r.get("importance", ""),
                "ステータス": "",
                "担当者": r.get("main_owner_name", ""),
                "担当者アドレス": r.get("main_owner_email", ""),
                "概要": r.get("summary", ""),
                "メッセージリンク": r.get("permalink", ""),
                "スレッド要約": r.get("thread_summary", ""),
                "備考": "",
            }
        )
    return rows
