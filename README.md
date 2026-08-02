# トレンドソング権利 ＆ アナリティクス統合データメディア 構築・全自動運用手順書

---

## 0. システムアーキテクチャ ＆ 設計思想

```text
【自動収集・自己増殖・ファクト記録パイプライン (Git Push時 ＆ 毎日夜24時実行)】
[GitHub Actions] ──► [YouTube Data API v3 (JP/Music急上昇 15件リアルタイム取得)]
        │
        ├─► [1. Gemini API 15件一括バッチ解析] (クォータ消費1/15化 ＆ 多重モデルフォールバック)
        │     レーベル名(HYBE/SMTOWN/ジュニアCHANNEL/Topic等)回避、引用符/カッコ解析による真の演者・曲名分離
        │
        ├─► [2. iTunes API交差照合 ＆ 誤爆防止フィルタ] JASRAC/NexTone手動照合用公式クエリ確定
        ├─► [3. MusicBrainz API 2段階ファクト照合] (limit=50 / 30秒タイムアウト＋5秒リトライ)
        │     ・演者完全一致 ➔ ISWCコード確定
        │     ・演者不一致 ➔ 切り捨てず「参考候補:T-xxx」コードおよび一次ソースURLを記録
        ├─► [4. 全曲ダイレクト手動照合導線生成] 
        │     ・JASRAC/NexTone手動照合URL (Google検索ダイレクト導線)
        │     ・MusicBrainz曲名ダイレクト検索URL (`work:"曲名"`)
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
        ├─► B2C Web画面 (`/`)：手動照合キーワード＋原盤権対策ボタン＋E-E-A-T信頼性カード＋Dataset JSON-LD
        ├─► B2B APIエンドポイント (`/api/v1/songs.json`)：Astro 静的プリレンダー (`prerender = true`)
        └─► デジタル資産販売 (`public/downloads/`)：一括CSVエクスポート販売
```

### 🌟 コア設計思想（開発・運用原則）

#### 1. 主観的断定（OK/NG）の徹底排除（ファクトベース主義）
* システム側で軽率に「配信許諾OK」などの判定を下さず、「どの検索ワードで照合し、どのコード（ISWC）が取得できたか（あるいは手動検索用リンク）」という**客観的事実（ファクト）とエビデンスURLのみを記録・提示**します。
* 最終判断をユーザー（クリエイター）に安全に委ねる構造にすることで、誤判定による著作権侵害トラブルからユーザーおよび運営者を完全に保護します。

#### 2. 「切り捨てない」ユーザー親切主義（手動照合導線の徹底）
* 権利コードが完全確定しなかった場合（未取得・新曲・同名異曲など）であっても、データを切り捨てて「コードなし」で放置しません。
* **「MusicBrainzダイレクト曲名検索URL」** や **「JASRAC/NexTone手動照合URL」** を全データに必ず付与し、コードが未確定でも**ユーザーが1秒（ワンクリック）で手動確認を完了できる導線**を担保します。
* 同名異曲が存在する場合は、参考候補（`参考候補:T-xxx`）として一次ソースURLとともに親切に提示します。

#### 3. 著作権と原盤権の分離管理（BANリスク回避）
* 著作物（作詞・作曲）の識別情報を提供しつつ、CD音源等の無断使用による原盤権侵害（アカウントBAN）を防ぐため、**「歌枠用カラオケ音源ダイレクト検索URL」**を標準装備しています。

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
│   └── fetch_data.py               # ★【全自動処理】Gemini一括解析・iTunes照合・MusicBrainz 2段階照合・ダイレクトURL生成
├── src/                            # Astro フロントエンド
│   ├── data/
│   │   ├── rights_master.json      # ★【自動増殖・補正】累積マスターデータベース (初期値: [])
│   │   └── songs.json              # ★【自動更新】表示・API用JSON (初期値: [])
│   └── pages/
│       ├── api/
│       │   └── v1/
│       │       └── songs.json.ts   # 【SSG Native API】静的プリレンダーREST APIエンドポイント
│       └── index.astro             # 【超軽量・リッチUI】B2C Web画面 ＆ E-E-A-Tカード ＆ Dataset JSON-LD
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
1. **YouTube 急上昇取得**: 日本地域の「音楽（カテゴリ10）」急上昇上位15件の動画メタデータ（タイトル、チャンネル名、再生数、高評価数、コメント数、投稿日）を取得。
2. **Gemini API 15件一括バッチ解析**: 
   * 15曲を**1回のリクエスト**にまとめて送信（クォータ消費を1/15に削減）。
   * `gemini-flash-lite-latest` ➔ `gemini-flash-latest` ➔ `gemini-2.0-flash` ➔ `gemini-2.0-flash-lite` の順で多重フォールバック試行（429/404エラーを全自動回避）。
   * チャンネル名（`HYBE` `SMTOWN` `THE FIRST TAKE` `Release - Topic` 等）を排除し、動画タイトルから真の「原曲名」と「原曲アーティスト」を抽出。カバー動画の原曲者も高精度分離。
3. **iTunes API 公式表記確定**:
   * アーティスト名からCV表記やカッコを除去し、JASRAC/NexToneポータル照合用の正体表記を確定。誤爆防止フィルタで無関係な曲への誤書き換えを防止。
4. **MusicBrainz API 2段階ファクト照合**:
   * タイムアウト 30秒 ＆ 503負荷発生時の 5秒待機自動リトライ。
   * 曲名クエリ（`work:"曲名"`）で上限50件（`limit=50`）を広域取得。
   * **第1段階（確定照合）**: 演者名が合致するワークを探索し、存在すれば `ISWC:T-xxx` コードを確定。
   * **第2段階（親切フォールバック）**: 演者不一致であっても曲名が一致するISWCコードがあれば切り捨てず `参考候補:T-xxx` コードとして記録し、エビデンスURLを保持。
5. **手動照合URL ＆ 原盤権導線の常時生成**:
   * 情報源表記からYouTubeを完全に排除し、**MusicBrainz曲名ダイレクト検索URL**（`https://musicbrainz.org/search?query=work:"曲名"&type=work`）へ統一。
   * **JASRAC/NexTone手動照合用URL**（Google検索ダイレクトリンク）および**歌枠用カラオケ音源ダイレクト検索URL**を全データに自動付与。
6. **マルチファイルエクスポート**:
   * マスターDB（`rights_master.json`）、表示用JSON（`songs.json`）、GEOガイド（`llms.txt`）、全6カラム統合構成のUTF-8 BOM付きCSV（`viral_song_rights_master.csv`）を一括出力。

### 3.2 CSVデータ構成（全6カラム統合フォーマット）

| カラム名 | 含まれるデータ内容・フォーマット |
| :--- | :--- |
| **1. トレンド動画タイトル** | YouTube生タイトル ＋ チャンネル名（`動画タイトル (チャンネル: チャンネル名)`） |
| **2. 再生数 / 反応率** | 総再生数 ｜ エンゲージメント率（%） ｜ 日速再生数 |
| **3. 権利コード / 許諾ステータス** | 識別コード（`ISWC:T-xxx` または `参考候補:T-xxx`） ｜ 照合ステータス |
| **4. JASRAC/NexTone 検索用キーワード** | JASRAC照合用曲名 ｜ 歌手名 ｜ Google手動照合ダイレクトURL |
| **5. 情報源 / 期限** | MusicBrainz曲名ダイレクト検索URL ｜ 権利確認日 ｜ 有効期限 *(※YouTube排除)* |
| **6. 原盤権対策 (音源)** | 歌枠用カラオケ音源ダイレクト検索URL |

---

## 4. フロントエンド ＆ エッジ配信仕様

### 4.1 B2C Web画面 (`src/pages/index.astro`)
* **SSG Native**: Astroによる事前静的生成。表示速度最優先の超軽量HTML。
* **E-E-A-T信頼性表示**: MusicBrainzレジストリ（MetaBrainz Foundation）の客観性・ISWCコードの一次情報性を明記。
* **原盤権注意書き**: 著作権（包括契約）と原盤権（市販音源使用リスク）の違いを警告し、カラオケ音源導線を提供。
* **Dataset Schema.org (JSON-LD)**: 検索エンジンおよびAIクローラー向けに `Dataset` / `MusicComposition` 構造化データを埋め込み。
* **収益化導線**: CSVデータセット一括ダウンロード（有料販売用）および推奨配信機材（アフィリエイト）枠を設置。

### 4.2 B2B API エンドポイント (`src/pages/api/v1/songs.json.ts`)
* `prerender = true` により、Astroビルド時に静的JSONとして事前生成。
* エッジCDNから高速配信され、サーバーレス関数の呼び出しコストがゼロ。

---

## 5. 全自動運用フロー (GitHub Actions ＆ Vercel)

### 5.1 自動化ワークフロー (`.github/workflows/update-db.yml`)
* **起動トリガー**:
  * `main` ブランチへの Git Push
  * 毎日日本時間 24:00 (`0 15 * * *` UTC) の Cron スケジュール
  * GitHub画面からの手動実行 (`workflow_dispatch`)
* **[skip ci] による無限ループ防止**:
  * ワークフロー内で更新データをコミットする際、コミットメッセージ末尾に `[skip ci]` を付与。自身がPushした更新によってCIが再度トリガーされる無限ループを防止。

### 5.2 運用サイクル
1. 毎日24:00にGitHub Actionsが起動し、`scripts/fetch_data.py` を実行。
2. データが更新された場合、GitHubへ `[skip ci]` 付きでコミット＆Push。
3. VercelがGitHubのPushを検知し、Astroサイトを自動静的ビルドして世界中のエッジサーバーへ即座にデプロイ。
4. **完全無人運用**で、Webメディア・API・データ販売用CSV・llms.txt のすべてが最新状態で維持され続ける。

---

## 6. 免責事項 ＆ 運用上の注意点

* **データの性質**: 本システムが提供する情報は、公開APIおよび国際レジストリ等から機械的に集約・照合したファクトデータです。
* **利用者の自己責任**: 楽曲の著作権管理状況（信託範囲や自己管理曲など）および原盤利用規約は変更される可能性があるため、利用者が商用配信やカバー制作を行う際は、必ず本システムが提供するダイレクト照合URLを活用し、権利管理団体（JASRAC/NexTone等）および音源権利者の公式ポータルにて個別確認を行ってください。