# トレンドソング権利 ＆ アナリティクス統合データメディア 構築・全自動運用手順書

---

## 0. システムアーキテクチャ ＆ 設計思想

```text
【自動収集・自己増殖・ファクト記録パイプライン (Git Push時 ＆ 毎日夜24時実行)】
[GitHub Actions] ──► [YouTube Data API v3 (JP/Music急上昇 15件リアルタイム・動画URL取得)]
        │
        ├─► [1. Gemini API 15件一括バッチ解析] (クォータ消費1/15化 ＆ 多重モデルフォールバック)
        │     レーベル名(HYBE/SMTOWN/ジュニアCHANNEL/Topic等)回避、引用符/カッコ解析による真の演者・曲名分離
        │
        ├─► [2. iTunes API交差照合 ＆ 誤爆防止フィルタ] JASRAC/NexTone手動照合用公式クエリ確定
        ├─► [3. MusicBrainz API 2段階ファクト照合] (limit=50 / inc=artist-rels+recording-rels 付与)
        │     ・演者完全一致 ➔ ISWCコード確定 ➔ ステータス：「ISWCコード確認済み」
        │     ・演者不一致/未登録 ➔ 切り捨てず「参考候補:T-xxx」記録 ➔ ステータス：「手動検索を推奨」
        ├─► [4. 全曲ダイレクト手動照合導線生成] 
        │     ・JASRAC/NexTone手動照合URL (Google検索ダイレクト導線)
        │     ・MusicBrainz曲名ダイレクト検索URL (ノイズ・work表記を排した `"曲名"` クエリ)
        ├─► [5. 原盤権対策] 歌枠用カラオケ音源ダイレクト検索URL自動生成
        │
        ├─► マスターDB自動拡張・補正 (`src/data/rights_master.json`) ★自動マイグレーション
        ├─► 日次Web用データ生成 (`src/data/songs.json`)
        ├─► GEO用AI標準規格ガイド生成 (`public/llms.txt`)
        └─► デジタル販売用CSV生成 (`public/downloads/viral_song_rights_master.csv`) ★全6カラム統合構成
        │
【ビルド・即時公開】
[Vercel (静的エッジ配信)] ◄── (Git Push検知) ── [Astro (超軽量SSG)]
        │
        ├─► B2C Web画面 (`/`)：動画直リンク＋手動照合キーワード＋原盤権対策ボタン＋E-E-A-T信頼性カード
        ├─► B2B APIエンドポイント (`/api/v1/songs.json`)：Astro 静的プリレンダー (`prerender = true`)
        └─► デジタル資産販売 (`public/downloads/`)：一括CSVエクスポート販売
```

### 🌟 コア設計思想（開発・運用原則）

#### 1. 主観的断定（OK/NG）の徹底排除（ファクトベース主義）
* システム側で「許諾OK」などの独自判定を下さず、国際標準識別コード（ISWC）の取得事実と、公認ポータルでの**客観的事実（ファクト）およびエビデンスURLのみを提示**します。
* 許諾ステータス表記は混乱を防ぐため **「ISWCコード確認済み」** と **「手動検索を推奨」** の**2通りに厳密限定**します。

#### 2. 「切り捨てない」ユーザー親切主義（手動照合導線の徹底）
* 権利コードが完全確定しなかった場合であっても、データを破棄せず「手動検索を推奨」として保持します。
* 括弧や記号を含む曲名（例: `WHATCHA DOIN` など）でもWeb検索が崩れないよう最適化した **「MusicBrainzダイレクト検索URL」** や **「JASRAC/NexTone照合URL」** を全データに付与し、ユーザーが**ワンクリックで手動確認を完了できる導線**を担保します。

#### 3. 著作権と原盤権の分離管理（BANリスク回避）
* 作詞・作曲の権利（著作権）の識別情報を提供しつつ、CD音源等の無断使用による原盤権侵害（アカウントBAN）を防ぐため、**「歌枠用カラオケ音源ダイレクト検索URL」** を標準装備しています。

---

## 1. ディレクトリ構造 ＆ 各ファイルの役割

```text
viral-song-rights-db/
├── .github/
│   └── workflows/
│       └── update-db.yml          # Git Pushトリガー・Cron(日次24:00)・[skip ci]無限ループ防止ワークフロー
├── public/                         # 静的配信領域
│   ├── downloads/
│   │   └── viral_song_rights_master.csv  # ★【自動生成】全6カラム統合構成の販売用CSV (UTF-8 BOM付き)
│   ├── llms.txt                    # ★【自動生成】GEO/AIクローラー向け構造化テキストガイド
│   └── robots.txt                  # AIクローラー許可設定
├── scripts/                        # バックエンドデータパイプライン
│   └── fetch_data.py               # ★【全自動処理】YouTube動画URL取得・Gemini解析・MusicBrainz精密照合・ダイレクトURL生成
├── src/                            # Astro フロントエンド
│   ├── data/
│   │   ├── rights_master.json      # ★【自動増殖・補正】累積マスターデータベース (初期値: [])
│   │   └── songs.json              # ★【自動更新】表示・API用JSON (初期値: [])
│   └── pages/
│       ├── api/
│       │   └── v1/
│       │       └── songs.json.ts   # 【SSG Native API】静的プリレンダーREST APIエンドポイント
│       └── index.astro             # 【超軽量・リッチUI】動画直リンク対応 Web画面 ＆ Dataset JSON-LD
├── astro.config.mjs                # Astro静的出力設定 (output: 'static')
├── package.json
└── tsconfig.json
```

---

## 2. 環境構築 ＆ APIキー設定手順

### 手順 2.1：YouTube Data API v3（Google Cloud Console）
1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスし、プロジェクトを作成。
2. 「**YouTube Data API v3**」を有効化し、APIキーを発行。
3. APIキー制限設定で「YouTube Data API v3」のみに利用を制限。

### 手順 2.2：Gemini API（Google AI Studio・完全無料）
1. [Google AI Studio](https://aistudio.google.com/) にアクセスし、Googleアカウントでログイン。
2. **`[Get API key]`** ➔ **`[Create API key]`** で `AIzaSy...` から始まるAPIキーを発行・コピー（クレジットカード登録不要）。

### 手順 2.3：GitHub Secrets ＆ 書き込み権限設定
1. **GitHub Secret の登録**:
   * リポジトリ ➔ `[Settings]` ➔ `[Secrets and variables]` ➔ `[Actions]`
   * **`YOUTUBE_API_KEY`**: YouTube APIキーを設定
   * **`GEMINI_API_KEY`**: Gemini APIキーを設定
2. **Workflow 書き込み権限の許可（HTTP 403エラー対策）**:
   * リポジトリ ➔ `[Settings]` ➔ `[Actions]` ➔ `[General]`
   * 最下部の **「Workflow permissions」** で **`Read and write permissions`**（読み取りおよび書き込み権限）を選択して **[Save]**。

---

## 3. データパイプライン（`scripts/fetch_data.py`）仕様

### 3.1 処理フロー
1. **YouTube 急上昇取得**:
   * 日本地域の「音楽（カテゴリ10）」急上昇上位15件のメタデータ（動画URL、タイトル、チャンネル名、再生数、反応率、投稿日）を取得。
2. **Gemini API 15件一括バッチ解析**:
   * 15曲を**1回のリクエスト**にまとめて送信（クォータ消費を1/15に削減）。
   * `gemini-flash-lite-latest` ➔ `gemini-flash-latest` ➔ `gemini-2.0-flash` ➔ `gemini-2.0-flash-lite` の順でフォールバック。ノイズ（公式チャンネル名、カバー表記等）を除去し真の「原曲名」と「演者名」を分離。
3. **iTunes API 公式表記確定**:
   * アーティスト名からCV表記やカッコを除去し、JASRAC/NexTone照合用の正体表記を確定。誤爆防止フィルタ適用。
4. **MusicBrainz API 精密ファクト照合**:
   * `inc=artist-rels+recording-rels` をリクエストに付与し、楽曲に紐づく演奏者・歌手情報を含めて取得。
   * **確定条件**: 演者名が一致するワークが存在する場合 ➔ **`ISWC:T-xxx`** 確定（ステータス: `ISWCコード確認済み`）。
   * **フォールバック**: 演者不一致・コード未アサインの場合 ➔ **`参考候補:T-xxx`** または **`コード未取得`**（ステータス: `手動検索を推奨`）。
5. **ダイレクト検索URLの最適化生成**:
   * Web用ダイレクトリンクには `work:` 等の検索エンジン阻害ノイズを含めず、**`"曲名"`（ダブルクォーテーション囲み）** のみにURLエンコードして生成（スペースや括弧を含む楽曲での崩れを防止）。
   * JASRAC/NexTone照合URLおよび歌枠用カラオケ音源URLを常時生成。
6. **マルチファイルエクスポート**:
   * `rights_master.json`、`songs.json`、`llms.txt`、およびUTF-8 BOM付きCSV（`viral_song_rights_master.csv`）を一括出力。

### 3.2 CSVデータ構成（全6カラム統合フォーマット）

| カラム名 | 含まれるデータ内容・フォーマット |
| :--- | :--- |
| **1. トレンド動画** | YouTube生タイトル ＋ チャンネル名 ＋ 直リンク動画URL |
| **2. 再生数 / 反応率** | 総再生数 ｜ エンゲージメント率（%） ｜ 日速再生数 |
| **3. 権利コード / 許諾ステータス** | 識別コード（`ISWC:T-xxx` / `参考候補` / `未取得`） ｜ `ISWCコード確認済み` or `手動検索を推奨` |
| **4. JASRAC/NexTone 検索用キーワード** | JASRAC照合用曲名 ｜ 歌手名 ｜ Google手動照合ダイレクトURL |
| **5. 情報源 / 期限** | MusicBrainz曲名ダイレクト検索URL ｜ 権利確認日 ｜ 有効期限 |
| **6. 原盤権対策 (音源)** | 歌枠用カラオケ音源ダイレクト検索URL |

---

## 4. フロントエンド ＆ エッジ配信仕様

### 4.1 B2C Web画面 (`src/pages/index.astro`)
* **トレンド動画直リンク対応**: 第1カラム「トレンド動画」のタイトルをクリックすると、YouTubeの対象動画（`https://www.youtube.com/watch?v=...`）へ直接遷移。
* **許諾ステータスバッジ**: 表示バッジを `ISWCコード確認済み`（緑）と `手動検索を推奨`（黄）の2種類に統一。
* **E-E-A-T信頼性表示 ＆ 原盤権注意書き**: MetaBrainz Foundation（ISWC）の客観性と、市販音源使用（原盤権侵害）のリスク警告を明記。
* **Dataset Schema.org (JSON-LD)**: 検索エンジン・AIクローラー向け構造化データを自動埋め込み。

### 4.2 B2B API エンドポイント (`src/pages/api/v1/songs.json.ts`)
* `prerender = true` により、Astroビルド時に静的JSONとして事前生成され、高速配信を実現。

---

## 5. 全自動運用フロー (GitHub Actions ＆ Vercel)

### 5.1 自動化ワークフロー (`.github/workflows/update-db.yml`)
* **起動トリガー**:
  * `main` ブランチへの Git Push
  * 毎日日本時間 24:00 (`0 15 * * *` UTC) の Cron スケジュール
  * 手動実行 (`workflow_dispatch`)
* **[skip ci] による無限ループ防止**:
  * データコミット時のメッセージ末尾に `[skip ci]` を付与し、CIの自己無限トリガーを防止。

### 5.2 運用サイクル
1. 毎日24:00にGitHub Actionsが起動し、`scripts/fetch_data.py` が自動実行。
2. 更新データを `[skip ci]` 付きでコミット＆Push。
3. VercelがPushを検知し、AstroサイトおよびAPI、CSV、`llms.txt` を自動静的ビルドして即座にエッジ配信。

---

## 6. 免責事項 ＆ 運用上の注意点

* **データの性質**: 本システムが提供する情報は、公開APIおよび国際レジストリ等から機械的に集約・照合したファクトデータです。
* **利用者の自己責任**: 楽曲の著作権管理状況（信託範囲や自己管理曲など）および原盤利用規約は変動する可能性があるため、利用者がカバー制作や配信を行う際は、本システムが提供するダイレクト照合URLを活用し、権利管理団体（JASRAC/NexTone等）および音源権利者の公式ポータルにて最終確認を行ってください。

---

## 7. Google Antigravity による自律開発 ＆ 運用保守手順

本プロジェクトの開発・コードリファクタリング・デバッグ・機能拡張においては、Googleの自律型AIエージェントプラットフォーム **「Google Antigravity」（Antigravity IDE / CLI / Agent）** を活用することで、人間が手動でコードを記述することなく自律的にシステム開発・保守を実行できます。

### 7.1 Antigravity の初期セットアップ
1. **インストール**:
   * [Google Antigravity 公式サイト](https://antigravity.google/) より `Antigravity IDE`（または Antigravity 2.0 スタンドアロンアプリ）をダウンロードしインストール。
2. **アカウント連携**:
   * アプリ起動後、右上 `[Log in with Google]` より Google アカウントでログイン。
3. **ワークスペースの作成**:
   * 本リポジトリのルートフォルダ（`viral-song-rights-db`）を Antigravity で開く。
4. **モデル選択**:
   * エージェントのメインAIモデルとして `Gemini 3 Pro` または `Gemini 3 Flash` を選択。

---

### 7.2 Antigravity によるプロンプト指示・自動開発手順

Antigravity では、自然言語で指示（プロンプト）を与えるだけで、エージェントが自律的にファイルの読込・構文解析・コード修正・ターミナルコマンド実行・ブラウザテストまでを一貫して代行します。

#### 【ケース①】データパイプライン（Python）の改修・バグ修正
1. **指示例**:
   > 「`scripts/fetch_data.py` を解析し、MusicBrainz API の Web 検索ダイレクトリンクから `work:` 表記を完全に除去してください。また、`WHATCHA DOIN` のようにスペースや括弧が含まれるタイトルでもURLエンコードが崩れないよう正規化処理を追加してください。」
2. **Antigravity の自律動作**:
   * エージェントが `scripts/fetch_data.py` を自動検索・読込。
   * プランニング（計画立案）を行い、コード差分を生成。
   * **Artifacts（成果物パネル）** にて修正コードの Visual Diff（差分）を表示。
3. **安全確認と承認**:
   * 人間が画面上で Artifacts のコード差分を確認し、`[Accept]` または `[Run Terminal]` を承認クリック。

#### 【ケース②】フロントエンド（Astro）UI・テーブルレイアウトの変更
1. **指示例**:
   > 「`src/pages/index.astro` のデータテーブルを修正してください。第1カラムの見出しを『1. トレンド動画』に変更し、タイトルをクリックすると `song.video_url`（YouTube動画）へ別タブで遷移するようにハイパーリンク化してください。」
2. **Antigravity の自律動作**:
   * Astro ファイルおよび TypeScript インターフェース（`Song`）を自動修正。
   * ターミナルで `npm run build` を自律実行し、ビルドエラーが発生しないかを自動検証。

---

### 7.3 Agentic SDLC（システム開発ライフサイクルの全自動化）

Antigravity 2.0 の多重エージェント機能（Multi-Agent）および CLI / SDK を活用した定型運用手順です。

```text
[開発・保守タスクの自然言語指示]
        │
        ▼
[Antigravity Agent (Planner)] ──► Codebase全読み込み ＆ 課題特定
        │
        ├─► [Coder Agent] ──────► Python/Astro コードの自動書き換え
        ├─► [Tester Agent] ─────► ターミナルで `python scripts/fetch_data.py` 実行・テスト
        └─► [Reviewer Agent] ───► 生成結果 (songs.json / CSV) の妥当性自動レビュー
        │
        ▼
[Artifacts (成果物表示)] ───────► 人間による1クリック最終確認 ➔ Git Commit & Push
```

1. **ローカル環境テストの自動化**:
   * エージェントに「`python scripts/fetch_data.py` を実行して生成された `songs.json` と CSV のフォーマットが正しいかテストして」と指示。
   * ターミナルでのテスト実行結果・ログを解析し、構文エラー（SyntaxError等）が発生した場合はAIが自律的に即座に自己修復。
2. **運用コードレビュー ＆ セキュリティチェック**:
   * APIキーがコード内にハードコーディングされていないか（`os.environ.get()` を使用しているか）を AI Agent が常時監視。
3. **Vercel デプロイ前の自動ビルドテスト**:
   * `npx astro build` をエージェントが裏で実行し、SSGプリレンダーエラー（`songs.json.ts` や `index.astro`）がないかを完全に自動で事前検証。