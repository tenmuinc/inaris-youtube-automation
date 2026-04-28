"""YouTube Data API v3 クライアント (Streamlit Web Hosting版)。

責務:
- OAuth2 認証 (Web flow / セッション保持)
- 21言語の字幕アップロード
- 21言語のローカライズタイトル・概要欄設定
- 公開時刻の予約
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def build_flow(client_config: dict, redirect_uri: str) -> Flow:
    """OAuth Web flow を構築する。

    client_config: Google Cloud Consoleで発行したOAuthクライアント(ウェブアプリ)のJSON。
                   通常は `{"web": {...}}` の形式。
    redirect_uri:  Google Cloud側に登録済みのリダイレクトURI。
    """
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def credentials_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def credentials_from_dict(data: dict) -> Credentials:
    return Credentials(**data)


class YouTubeClient:
    """既に認証済みの Credentials を受け取り、APIを叩くだけのクライアント。"""

    def __init__(self, credentials: Credentials):
        if not credentials.valid:
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                raise RuntimeError("YouTube OAuth credentials が無効です。再認証してください。")
        self._credentials = credentials
        self._service = build("youtube", "v3", credentials=credentials)

    @property
    def credentials(self) -> Credentials:
        return self._credentials

    @property
    def service(self):
        return self._service

    def schedule_publish(self, video_id: str, publish_at: str) -> None:
        """既にアップロード済みの動画に公開予約時刻を設定する。"""
        self.service.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": publish_at,
                    "selfDeclaredMadeForKids": False,
                },
            },
        ).execute()

    def upload_caption(
        self, video_id: str, language_code: str, srt_path: str | Path, name: str = ""
    ) -> str:
        """1言語分のSRTをアップロード。caption IDを返す。"""
        media = MediaFileUpload(
            str(srt_path), mimetype="application/octet-stream", resumable=False
        )
        response = (
            self.service.captions()
            .insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "language": language_code,
                        "name": name,
                        "isDraft": False,
                    }
                },
                media_body=media,
            )
            .execute()
        )
        return response["id"]

    def set_localizations(
        self,
        video_id: str,
        default_language: str,
        default_title: str,
        default_description: str,
        localizations: dict[str, dict[str, str]],
        category_id: str = "22",
    ) -> None:
        """21言語分のローカライズタイトル・概要欄をまとめて設定する。"""
        self.service.videos().update(
            part="snippet,localizations",
            body={
                "id": video_id,
                "snippet": {
                    "title": default_title,
                    "description": default_description,
                    "categoryId": category_id,
                    "defaultLanguage": default_language,
                },
                "localizations": localizations,
            },
        ).execute()

    def find_caption_files(
        self, srt_dir: str | Path, languages: list[dict]
    ) -> dict[str, Path]:
        """SRTディレクトリから言語コード→ファイルパスの辞書を返す。

        macOSのNFD正規化対策込み。
        """
        import unicodedata

        srt_dir = Path(srt_dir)
        all_srts = list(srt_dir.rglob("*.srt"))
        normalized = [
            (p, unicodedata.normalize("NFC", p.stem)) for p in all_srts
        ]
        result = {}
        for lang in languages:
            suffix_nfc = unicodedata.normalize("NFC", lang["vrew_suffix"])
            for path, stem_nfc in normalized:
                if stem_nfc.endswith(suffix_nfc):
                    result[lang["code"]] = path
                    break
        return result
