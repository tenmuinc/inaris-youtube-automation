# inaris-youtube-automation

INARIS の YouTube 動画制作で繰り返し作業の多い「AI字幕生成」「21言語タイトル＆概要欄生成」「YouTubeへの21言語字幕アップロード＆公開予約」を一括処理する Streamlit アプリ。

Streamlit Community Cloud にデプロイ済み。社内メンバーは URL を開くだけで使える。

## 機能

- **STEP 1 — AI字幕生成**: ルビ振り前の日本語SRT → Native Vibe / JLPT / 21言語タイトル＆概要欄
- **STEP 2 — YouTube投稿予約**: 21言語SRT + titles.json → 21言語字幕アップ + ローカライズタイトル + 公開時刻予約

動画ファイル本体は YouTube Studio で先にアップしておき、Video ID をこのアプリに渡す（クラウド側の負荷とアップロード制限を避けるため）。

## デプロイ手順

### 1. Google Cloud Console で OAuth クライアント (ウェブアプリケーション) を作成

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクト
2. **APIとサービス → ライブラリ → "YouTube Data API v3" を有効化**
3. **APIとサービス → OAuth同意画面**: 外部 → 必要事項記入 → テストユーザーに利用メンバーのGoogleメールを追加
4. **APIとサービス → 認証情報 → 認証情報を作成 → OAuth クライアント ID**
   - 種類: **ウェブアプリケーション**
   - 承認済みのリダイレクトURI: `https://<your-app>.streamlit.app/`（デプロイ後のURL）
5. ダウンロードしたJSONの `"web"` セクションを Streamlit Secrets に転記する

### 2. Anthropic APIキー取得

[console.anthropic.com](https://console.anthropic.com/) で発行。Plans & Billing で支払い設定。

### 3. リポジトリを Streamlit Community Cloud に接続

1. [share.streamlit.io](https://share.streamlit.io/) にログイン
2. **New app** → このGitHubリポジトリを選択 → メインファイル `app.py`
3. デプロイ後、アプリ設定 → **Secrets** に `.streamlit/secrets.toml.example` の内容を埋めて貼り付け
4. アプリURLを Google Cloud Console のリダイレクトURIに登録（手順1.5）

### 4. アクセス制御

Google OAuth 同意画面で **テストユーザー** に追加した Google アカウントだけが認証できる。新メンバー追加は Google Cloud Console から。

## ローカル動作確認

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .streamlit/secrets.toml に .streamlit/secrets.toml.example をコピーして埋める
# redirect_uri は http://localhost:8501 にし、Google Cloud側にも同じURLを登録

streamlit run app.py
```

## ファイル構成

```
.
├── app.py                       # Streamlit UI 本体
├── core/
│   ├── youtube_client.py        # YouTube API ラッパー (Web OAuth対応)
│   ├── claude_client.py         # Claude API ラッパー
│   └── srt_utils.py             # SRT解析・ルビ検知
├── requirements.txt
├── .streamlit/
│   └── secrets.toml.example     # Secrets テンプレート (Streamlit Cloud側に貼る)
└── README.md
```

## ユーザー向けマニュアル

利用手順（撮影〜投稿予約までの全工程）は社内Notionの「[INARIS YouTube 全手順マニュアル](https://www.notion.so/350f29fee2808172a5d1e80cc885a3d9)」を参照。
