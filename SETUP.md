# 検知くん GitHub Actions 構築手順

## 全体像

```
GitHub Actions (cron: 月〜金 10/12/14/16/18/20 JST)
  ├─ scripts/run_claim_detection.py     (クレーム検知くん)
  └─ scripts/run_churn_detection.py     (解約リスク検知くん)
       │
       ├─ Slack API（社内/社外チャンネル検索 → スレッド取得 → 通知送信）
       ├─ Anthropic API via OAuth refresh（Claude Codeサブスク経由＝追加費用なし）
       └─ Google Sheets API（gspreadサービスアカウント）
```

## 必要な Secrets（GitHub リポジトリに登録）

| Secret 名 | 用途 | 取得元 |
|---|---|---|
| `CLAUDE_REFRESH_TOKEN` | Claude OAuth リフレッシュトークン | `~/.claude/.credentials.json` |
| `CLAUDE_CREDENTIALS` | 上の元データ全体（バックアップ用） | 同上 |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) | Slack App 管理画面 |
| `GOOGLE_SHEETS_KEY` | Google Cloud サービスアカウント JSON 全文 | GCP Console |
| `ANTHROPIC_API_KEY` | （オプション）OAuth が動かない時のフォールバック用 | Anthropic Console |

---

## ステップ 1: Google Cloud サービスアカウント作成

1. [Google Cloud Console](https://console.cloud.google.com/) を開く
2. 適当なプロジェクト（既存 or 新規）を選択
3. **IAM と管理 → サービスアカウント → 作成**
4. 名前: `claim-check-sheets-writer`
5. 役割は割り当て不要（スプシ側で個別共有するため）
6. 作成後、サービスアカウント詳細 → **「鍵」タブ → 鍵を追加 → JSON**
7. ダウンロードされた JSON ファイルを安全な場所に保存（後で Secrets に登録）

### Sheets API 有効化

1. **APIとサービス → ライブラリ**
2. 「Google Sheets API」を検索 → **有効にする**
3. 「Google Drive API」も同様に有効にする

### スプシをサービスアカウントに共有

1. [AI検知ログのスプシ](https://docs.google.com/spreadsheets/d/1NYuYHOCUM-Uog5VySQ5OiAVkB5HE6_BmYPKpuELqKWI/edit) を開く
2. 右上の **「共有」**
3. サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）を貼る
4. 権限: **編集者**
5. **送信**

---

## ステップ 2: Slack Bot 作成（または既存 Bot 流用）

amptalk チームの Bot を流用できるなら不要。新規作成する場合:

1. https://api.slack.com/apps → **Create New App** → From scratch
2. App Name: `検知くん`
3. **OAuth & Permissions → Bot Token Scopes** に追加:
   - `channels:history`
   - `groups:history`
   - `chat:write`
   - `search:read`
   - `users:read`
   - `users:read.email`
   - `channels:read`
   - `groups:read`
4. **Install to Workspace** → 承認
5. **Bot User OAuth Token (`xoxb-...`)** をコピー
6. 通知先・検索対象の各チャンネルに Bot を **/invite @検知くん** で招待

---

## ステップ 3: Claude OAuth トークンの取得

Claude Code でログイン済みなら `~/.claude/.credentials.json` に既に存在する。

```powershell
# 確認
Get-Content "$env:USERPROFILE\.claude\.credentials.json"
```

`claudeAiOauth.refreshToken` が **`CLAUDE_REFRESH_TOKEN`** の値になる。  
ファイル全体を **`CLAUDE_CREDENTIALS`** に入れる。

---

## ステップ 4: GitHub Secrets 登録

### 自動登録（推奨）

```powershell
cd C:\Users\risaki_iha\Repos\Claim_check
py scripts\update_claude_secret.py    # CLAUDE_REFRESH_TOKEN と CLAUDE_CREDENTIALS を一括登録
```

### 残りを手動登録

```powershell
# Slack Bot トークン
gh secret set SLACK_BOT_TOKEN --repo risaki-iha/Claim_check

# サービスアカウント JSON（中身全文をペースト）
gh secret set GOOGLE_SHEETS_KEY --repo risaki-iha/Claim_check < path\to\service-account.json
```

---

## ステップ 5: 動作確認

### ① 手動でワークフロー実行

```powershell
gh workflow run "クレーム検知くん" --repo risaki-iha/Claim_check
gh run list --repo risaki-iha/Claim_check --limit 3
gh run watch --repo risaki-iha/Claim_check
```

または GitHub Web UI の **Actions タブ → "Run workflow"**

### ② 確認項目

- [ ] Slack `#dxm_クレーム検知くん` (C0ABRS7NR27) に通知が届く
- [ ] スプシ「AI検知ログ」シートに行が追加される（検知ありの場合）
- [ ] 重要度フィルター（🔴🟡🔵）と「対応メンバー」が正しく入る

---

## ステップ 6: claude.ai routine の停止（並走期間後）

GitHub Actions が安定稼働を確認してから:

1. claude.ai → Routines → クレーム検知くん リアルタイム
2. ステータスを **無効化**（削除はしない、いつでも戻せるように）
3. 解約リスク検知くん リアルタイム も同様

---

## トラブルシューティング

| 症状 | 原因と対応 |
|---|---|
| OAuth 401 エラー | `update_claude_secret.py` を再実行してトークン更新 |
| Slack `not_in_channel` | Bot を対象チャンネルに `/invite` で招待 |
| Sheets `PERMISSION_DENIED` | スプシをサービスアカウントに編集権限で共有してるか確認 |
| 通知時刻範囲がおかしい | `scripts/lib/detector.py` の `parse_end_time_from_header` で正規表現を確認 |
| 全く検知されない | Bot のスコープ（`search:read` など）が足りない可能性 |

---

## ファイル構成

```
Claim_check/
├─ .github/workflows/
│   ├─ claim_detection.yml     # クレーム検知のcron
│   └─ churn_detection.yml     # 解約リスク検知のcron
├─ scripts/
│   ├─ run_claim_detection.py  # クレーム検知エントリポイント
│   ├─ run_churn_detection.py  # 解約リスク検知エントリポイント
│   ├─ refresh_credentials.py  # OAuth リフレッシュ実行（GitHub Actions用）
│   ├─ update_claude_secret.py # ローカル：Secrets更新ヘルパー
│   └─ lib/
│       ├─ detector.py         # 共通検知ロジック
│       ├─ claude_oauth.py     # Claude OAuth クライアント
│       ├─ slack_tools.py      # Slack API ラッパー
│       └─ sheets_tools.py     # gspread ラッパー
├─ skills/
│   ├─ claim-detection-realtime.md  # AI判定基準（クレーム）— 不変
│   └─ churn-detection-realtime.md  # AI判定基準（解約リスク）
├─ requirements.txt
├─ CLAUDE.md
└─ SETUP.md (このファイル)
```
