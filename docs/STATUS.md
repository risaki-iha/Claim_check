# 検知くん GitHub Actions 移行 — 現状とご相談

最終更新: 2026-05-11

リポジトリ: [`risaki-iha/Claim_check`](https://github.com/risaki-iha/Claim_check)

---

## 🎯 やりたいこと

社内 Slack の **クレーム検知 / 解約リスク検知** の自動通知システムを、
**月額追加コストなし** で **完全自動運用** したい。

具体的には:

- 平日 JST 10/12/14/16/18/20 に Slack の社内/社外チャンネルを横断検索
- AI（Claude）で重要度判定（🔴/🟡/🔵）
- 検知結果を Slack 通知 + スプレッドシート転記

---

## 🛠 やってること

### Before（〜先週）

claude.ai の routine（リモート Claude Code）で動かしてた。  
→ スプシ書き込みが不可能（Workspaceポリシーで Apps Script 公開不可・Sheets コネクタ無し）

### After（今）

**GitHub Actions + Python + Claude OAuth** に再構築。  
`amptalk-risk-detection` を参考にした構成。  
Claude API は **Code サブスクの OAuth トークン経由**で叩く（API Key 課金を回避）。

### 構成

```
GitHub Actions cron（"7 1,3,5,7,9,11 * * 1-5" UTC
                   = JST 月〜金 10:07/12:07/14:07/16:07/18:07/20:07）
  └─ scripts/run_*_detection.py
        ├─ skills/*.md を system prompt として読み込み（精度維持）
        ├─ Slack 検索（User Token xoxp- 使用。search.messages は Bot Token 非対応）
        ├─ チャンネルフィルター（社内_ / 社外_ のみ、mdx_ / dxm_ / hajimari は除外）
        ├─ スレッド取得 + 投稿者プロフィール
        ├─ Claude Messages API（OAuth Bearer + anthropic-beta: oauth-2025-04-20）で重要度判定
        ├─ Slack 通知投稿
        └─ gspread でスプシ append（GCPサービスアカウント）
```

### 動作確認できてるところ

| | 状態 |
|---|---|
| Slack 検索 〜 スレッド取得 〜 ユーザー判定 | ✅ |
| OAuth Bearer で `/v1/messages` 叩いて 200 で結果取得 | ✅ |
| Slack 通知投稿 | ✅ |
| スプシへの append | ✅（解約リスク側で 1件確認できた） |

---

## 🚨 引っかかってること：CLAUDE_REFRESH_TOKEN の自動ローテーション

### 症状

1. GitHub Actions が `CLAUDE_REFRESH_TOKEN`（Secret）で OAuth refresh
2. `POST https://api.anthropic.com/v1/oauth/token` （form-encoded）  
   → **200 で新 access_token + 新 refresh_token を取得**
3. 新 refresh_token は GitHub Actions プロセスのメモリ内にしか存在しない
4. Anthropic 側は古い refresh_token を **invalidate**
5. **GitHub Secret は古い値のまま** → 次回 workflow 実行時に  
   `invalid_grant: Refresh token not found or invalid` で 400

### 現状の回避策

毎回ローカルで以下を叩いて、`~/.claude/.credentials.json` の最新 refresh_token を GitHub Secret に再アップロード:

```bash
py scripts\update_claude_secret.py
```

これで動くけど、**cron 自動実行毎に毎回手動更新が必要** で運用に乗せられない。

### 試したこと

- `POST /v1/oauth/token` のリクエスト body を JSON → **form-encoded** に変更（200 帰るようになった）
- `Authorization: Bearer <access_token>` + `anthropic-beta: oauth-2025-04-20` ヘッダ追加
- 429/5xx で指数バックオフリトライ実装
- モデルを Sonnet 4.6 → Haiku 4.5 に変更（quota 食い緩和）

---

## 🙏 聞きたいこと

### Q1. amptalk チームは新 refresh_token を GitHub Secret に書き戻してますか？

`run_risk_detection.py` 内で OAuth refresh 成功後、新 refresh_token を `gh secret set CLAUDE_REFRESH_TOKEN` 的に書き戻してる？  
それとも別アプローチ？

### Q2. 書き戻すなら GitHub への認証は何？

- デフォルトの `GITHUB_TOKEN` だと `actions:secrets:write` 権限がない（と理解）
- Personal Access Token (PAT) を別 Secret として置いてる？ scope は？
- Fine-grained PAT or Classic PAT？

### Q3. もしくは別のアプローチで解決してる？

- 専用の "refresh だけする" cron workflow を別に用意してる？
- Anthropic API Key を併用してる？
- Service account 的な long-lived credential を発行してる？

### Q4. （副次的）Claude Code サブスクの quota について

直近で Sonnet 4.6 を 6 thread × 数回叩いたら 429（`rate_limit_error`）連発した。  
amptalk リスク検知でも 429 出てる？対策してる？

---

## 副次的にハマって解決したポイント（参考）

| ハマり | 解決 |
|---|---|
| Slack search 同日範囲で 0件 | `after:` `before:` は **exclusive**。`-1日 / +1日` の幅で投げて ts で再フィルタ |
| `search.messages` で `not_allowed_token_type` | **User Token 必須**。`SLACK_USER_TOKEN` を別 Secret 化 |
| `conversations.replies` で `not_in_channel` | Bot 未招待でも User 経由で読めるよう **User Token 優先 → Bot fallback** |
| PowerShell から Secret 登録すると **BOM 混入** で latin-1 encode 失敗 | `gh secret set --body "..."` で直接渡す or 受信側で `lstrip("﻿")` |
| Anthropic `/v1/oauth/token` で 400 | `json=` ではなく `data=` で **form-encoded** 送信 |

---

## 主要ファイル

| パス | 役割 |
|---|---|
| `scripts/lib/claude_oauth.py` | OAuth クライアント本体 |
| `scripts/lib/detector.py` | 検知ロジック共通部 |
| `scripts/lib/slack_tools.py` | Slack API ラッパー |
| `scripts/lib/sheets_tools.py` | gspread ラッパー |
| `scripts/run_claim_detection.py` | クレーム検知エントリポイント |
| `scripts/run_churn_detection.py` | 解約リスク検知エントリポイント |
| `scripts/update_claude_secret.py` | ローカル：Secret 更新ヘルパー |
| `scripts/refresh_credentials.py` | OAuth リフレッシュ実行（雛形） |
| `.github/workflows/claim_detection.yml` | クレーム検知 cron |
| `.github/workflows/churn_detection.yml` | 解約リスク検知 cron |
| `SETUP.md` | セットアップ手順 |
