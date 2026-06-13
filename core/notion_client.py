"""Notion API クライアント。

責務:
- 「動画管理」DB から M番号(ID列) で該当ページを検索
- title / description / srt / tips / schedule などのプロパティを更新

設計の肝:
- Notion DBはユーザーが手動で構造を変えうるので、プロパティが無くてもエラーにせず無視する
- token / database_id が未設定なら無効化（黙ってno-op）。STEP実行を阻害しない
"""

from __future__ import annotations

from typing import Optional

import requests


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionClient:
    def __init__(self, token: str, database_id: str):
        self.token = token
        self.database_id = database_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.database_id)

    def find_page_by_m_number(self, m_number: str) -> Optional[str]:
        """ID列(title型)がm_numberに一致するページのIDを返す。なければNone。"""
        # まずDBスキーマからtitle列の名前を引く
        url = f"{NOTION_API}/databases/{self.database_id}"
        try:
            r = requests.get(url, headers=self.headers, timeout=15)
            r.raise_for_status()
            db = r.json()
        except Exception:
            return None

        title_prop = None
        for name, meta in db.get("properties", {}).items():
            if meta.get("type") == "title":
                title_prop = name
                break
        if not title_prop:
            return None

        # クエリでm_numberに一致する行を探す
        query_url = f"{NOTION_API}/databases/{self.database_id}/query"
        body = {
            "filter": {
                "property": title_prop,
                "title": {"equals": m_number},
            },
            "page_size": 1,
        }
        try:
            r = requests.post(query_url, headers=self.headers, json=body, timeout=15)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception:
            return None

        if not results:
            return None
        return results[0]["id"]

    def update_video_metadata(
        self,
        m_number: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        srt: Optional[bool] = None,
        tips: Optional[bool] = None,
        schedule: Optional[str] = None,
    ) -> tuple[bool, str]:
        """該当ページを見つけて指定プロパティを更新する。

        Returns: (success, message)
        """
        if not self.enabled:
            return False, "Notion未設定"

        page_id = self.find_page_by_m_number(m_number)
        if not page_id:
            return False, f"M番号 {m_number} のページが見つかりません"

        # 該当DBに存在するプロパティだけセットする
        # （存在しないプロパティを送ると400で全部落ちる）
        url = f"{NOTION_API}/databases/{self.database_id}"
        try:
            r = requests.get(url, headers=self.headers, timeout=15)
            r.raise_for_status()
            db_props = r.json().get("properties", {})
        except Exception as e:
            return False, f"DBスキーマ取得失敗: {e}"

        props: dict = {}
        # text(rich_text) プロパティ
        if title is not None and "title" in db_props and db_props["title"]["type"] == "rich_text":
            props["title"] = {"rich_text": [{"type": "text", "text": {"content": title[:2000]}}]}
        if (
            description is not None
            and "description" in db_props
            and db_props["description"]["type"] == "rich_text"
        ):
            props["description"] = {
                "rich_text": [{"type": "text", "text": {"content": description[:2000]}}]
            }
        if (
            schedule is not None
            and "schedule" in db_props
            and db_props["schedule"]["type"] == "rich_text"
        ):
            props["schedule"] = {
                "rich_text": [{"type": "text", "text": {"content": schedule[:2000]}}]
            }
        # checkbox プロパティ
        if srt is not None and "srt" in db_props and db_props["srt"]["type"] == "checkbox":
            props["srt"] = {"checkbox": bool(srt)}
        if tips is not None and "tips" in db_props and db_props["tips"]["type"] == "checkbox":
            props["tips"] = {"checkbox": bool(tips)}

        if not props:
            return False, "更新可能なプロパティがありません"

        patch_url = f"{NOTION_API}/pages/{page_id}"
        try:
            r = requests.patch(
                patch_url,
                headers=self.headers,
                json={"properties": props},
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            return False, f"Notion更新失敗: {e}"

        return True, f"更新成功: {', '.join(props.keys())}"
