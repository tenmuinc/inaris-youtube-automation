"""inaris_youtube_automation - Streamlit Web版

Streamlit Community Cloudにデプロイ可能なWeb UI。
設定はすべて Streamlit Secrets (.streamlit/secrets.toml) から読む。
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

import streamlit as st

from core.claude_client import ClaudeClient
from core.srt_utils import (
    RubyContaminationError,
    build_jlpt_srt,
    build_native_vibe_srt,
    detect_ruby,
    parse_srt,
)
from core.youtube_client import (
    YouTubeClient,
    build_flow,
    credentials_from_dict,
    credentials_to_dict,
)


# ============================================================================
# 設定読み込み
# ============================================================================
def load_secrets():
    try:
        anthropic_api_key = st.secrets["anthropic_api_key"]
        anthropic_model = st.secrets.get("anthropic_model", "claude-sonnet-4-6")
        youtube_languages = [dict(x) for x in st.secrets["youtube_languages"]]
        google_oauth = dict(st.secrets["google_oauth"])
        redirect_uri = st.secrets["redirect_uri"]
        prompts = {
            "native_vibe": st.secrets["prompts"]["native_vibe"],
            "jlpt": st.secrets["prompts"]["jlpt"],
            "multilingual_titles": st.secrets["prompts"]["multilingual_titles"],
        }
    except (KeyError, FileNotFoundError) as e:
        st.error(
            "❌ Secretsが設定されていません。\n\n"
            "Streamlit Cloudのアプリ設定 → Secrets で以下を設定してください：\n"
            "- `anthropic_api_key`\n"
            "- `anthropic_model`（任意）\n"
            "- `redirect_uri`\n"
            "- `[google_oauth]` セクション\n"
            "- `[[youtube_languages]]` テーブル × 21\n"
            "- `[prompts]` セクション (native_vibe / jlpt / multilingual_titles)\n\n"
            f"不足キー: `{e}`"
        )
        st.stop()
    return {
        "anthropic_api_key": anthropic_api_key,
        "anthropic_model": anthropic_model,
        "youtube_languages": youtube_languages,
        "google_oauth": google_oauth,
        "redirect_uri": redirect_uri,
        "prompts": prompts,
    }


def safe_m_number(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", s) or "M0000"


def reset_step1():
    for k in ("step1_results", "step1_m_number", "step1_segments_count"):
        if k in st.session_state:
            del st.session_state[k]


# ============================================================================
# 画面設定
# ============================================================================
st.set_page_config(
    page_title="inaris_youtube_automation",
    page_icon="🎬",
    layout="centered",
)

st.markdown("# 🎬 inaris_youtube_automation")
st.caption("INARIS の YouTube 動画制作の繰り返し作業を一括自動化します。")

config = load_secrets()


# ============================================================================
# OAuth コールバック処理（クエリ ?code=xxx で戻ってきたとき）
# ============================================================================
def _client_config_for_flow(google_oauth: dict, redirect_uri: str) -> dict:
    """Google OAuth Flow.from_client_config が期待する形式に整える。"""
    return {
        "web": {
            "client_id": google_oauth["client_id"],
            "client_secret": google_oauth["client_secret"],
            "auth_uri": google_oauth.get(
                "auth_uri", "https://accounts.google.com/o/oauth2/auth"
            ),
            "token_uri": google_oauth.get(
                "token_uri", "https://oauth2.googleapis.com/token"
            ),
            "redirect_uris": [redirect_uri],
        }
    }


query = st.query_params
if "code" in query and "yt_credentials" not in st.session_state:
    try:
        flow = build_flow(
            _client_config_for_flow(config["google_oauth"], config["redirect_uri"]),
            config["redirect_uri"],
        )
        # PKCE: 認可URL生成時に保存した code_verifier を復元
        if "oauth_code_verifier" in st.session_state:
            flow.code_verifier = st.session_state["oauth_code_verifier"]
        flow.fetch_token(code=query["code"])
        st.session_state["yt_credentials"] = credentials_to_dict(flow.credentials)
        st.session_state.pop("oauth_code_verifier", None)
        st.query_params.clear()
        st.success("✅ Google認証に成功しました")
        st.rerun()
    except Exception as e:
        st.error(f"OAuthコールバック処理に失敗: {e}")
        st.stop()


# ============================================================================
# タブ
# ============================================================================
tab1, tab2 = st.tabs(["📝 STEP 1 — AI字幕を作る", "🚀 STEP 2 — YouTubeに投稿予約する"])


# ============================================================================
# STEP 1: AI字幕生成
# ============================================================================
with tab1:
    st.markdown("### STEP 1 — AI字幕を作る")
    st.markdown(
        """
        Vrewから書き出した**ルビ振り前の日本語SRT**から、3つのファイルを自動生成します：
        - `native_vibe_M####.srt` — Native Vibe字幕
        - `jlpt_vocab_M####.srt` — JLPT単語字幕
        - `titles_M####.json` — 21言語のタイトル＆概要欄
        """
    )

    if st.session_state.get("step1_results"):
        results = st.session_state["step1_results"]
        m_num = st.session_state["step1_m_number"]
        seg_count = st.session_state.get("step1_segments_count", 0)

        st.success(f"✅ 生成完了！ {seg_count} セグメントから以下を生成：")

        for kind, (filename, content_bytes, count) in results.items():
            label = {
                "native_vibe": f"🎙 Native Vibe : {count}件",
                "jlpt": f"📖 JLPT単語 : {count}件",
                "titles": f"🌐 多言語タイトル＆概要欄 : {count}言語",
            }[kind]
            with st.container(border=True):
                st.markdown(f"**{label}**")
                st.caption(filename)
                st.download_button(
                    label=f"⬇️ {filename} をダウンロード",
                    data=content_bytes,
                    file_name=filename,
                    mime="text/plain" if filename.endswith(".srt") else "application/json",
                    key=f"dl_{kind}",
                    use_container_width=True,
                )

        if st.button("🔄 最初に戻る", use_container_width=True, key="back_btn"):
            reset_step1()
            st.rerun()

    else:
        with st.container(border=True):
            st.markdown("##### 入力")

            m_number_input = st.text_input(
                "M番号",
                value="M0405",
                key="gen_m",
                help="案件番号。出力ファイル名に使われます",
            )
            m_number = safe_m_number(m_number_input)

            uploaded_srt = st.file_uploader(
                "日本語SRT（ルビ振り**前**）",
                type=["srt"],
                key="gen_srt",
                help="Vrewで本字幕作成 → ルビ振り前にダウンロードしたSRT",
            )

            st.markdown("##### 生成オプション")
            col1, col2, col3 = st.columns(3)
            gen_nv = col1.checkbox("Native Vibe", value=True, key="gen_nv_cb")
            gen_jlpt = col2.checkbox("JLPT単語", value=True, key="gen_jlpt_cb")
            gen_titles = col3.checkbox("21言語のタイトル＆概要欄", value=True, key="gen_titles_cb")

            generate_disabled = uploaded_srt is None or not any([gen_nv, gen_jlpt, gen_titles])
            generate_clicked = st.button(
                "🤖 AI字幕を生成する",
                type="primary",
                disabled=generate_disabled,
                use_container_width=True,
                key="gen_btn",
            )

        if generate_clicked:
            try:
                raw = uploaded_srt.getvalue().decode("utf-8-sig")

                ruby_found = detect_ruby(raw)
                if ruby_found:
                    raise RubyContaminationError(
                        f"このSRTにはルビ記法が混入しています: {ruby_found[:3]}"
                    )

                segments = parse_srt(raw)
                if not segments:
                    st.error("SRTが空、または読めませんでした。")
                    st.stop()

                client = ClaudeClient(
                    api_key=config["anthropic_api_key"],
                    prompts=config["prompts"],
                    model=config["anthropic_model"],
                )

                results = {}
                progress = st.progress(0.0, text="生成中...")
                steps_total = sum([gen_nv, gen_jlpt, gen_titles])
                step_done = 0

                if gen_nv:
                    progress.progress(step_done / steps_total, text="Native Vibe生成中...")
                    nv_items = client.generate_native_vibe(segments)
                    nv_srt = build_native_vibe_srt(segments, nv_items)
                    results["native_vibe"] = (
                        f"native_vibe_{m_number}.srt",
                        nv_srt.encode("utf-8"),
                        len(nv_items),
                    )
                    step_done += 1

                if gen_jlpt:
                    progress.progress(step_done / steps_total, text="JLPT単語生成中...")
                    jlpt_items = client.generate_jlpt(segments)
                    jlpt_srt = build_jlpt_srt(segments, jlpt_items)
                    results["jlpt"] = (
                        f"jlpt_vocab_{m_number}.srt",
                        jlpt_srt.encode("utf-8"),
                        len(jlpt_items),
                    )
                    step_done += 1

                if gen_titles:
                    progress.progress(
                        step_done / steps_total, text="21言語のタイトル＆概要欄生成中..."
                    )
                    titles = client.generate_multilingual_titles(segments)
                    results["titles"] = (
                        f"titles_{m_number}.json",
                        json.dumps(titles, ensure_ascii=False, indent=2).encode("utf-8"),
                        len(titles),
                    )
                    step_done += 1

                progress.progress(1.0, text="完了")

                st.session_state["step1_results"] = results
                st.session_state["step1_m_number"] = m_number
                st.session_state["step1_segments_count"] = len(segments)
                st.rerun()

            except RubyContaminationError as e:
                st.error(f"⚠️ ルビ混入を検出しました\n\n{e}")
                st.info(
                    "**対処法**: Vrewで「本字幕作成 → ルビ振り**前**にSRT書き出し」"
                    "の順番でやり直してください。"
                )
            except Exception as e:
                st.exception(e)


# ============================================================================
# STEP 2: YouTube投稿予約 (Video ID指定モードのみ)
# ============================================================================
with tab2:
    st.markdown("### STEP 2 — YouTubeに投稿予約する")
    st.markdown(
        """
        **動画は先に YouTube Studio にアップロード**しておき、Video ID をこの画面に渡します。
        以下を一括実行：
        - 21言語の字幕アップロード
        - 21言語のタイトル＆概要欄を設定
        - 公開時刻を予約
        """
    )

    # ---- OAuth セクション ----
    creds_dict = st.session_state.get("yt_credentials")

    if not creds_dict:
        flow = build_flow(
            _client_config_for_flow(config["google_oauth"], config["redirect_uri"]),
            config["redirect_uri"],
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline", prompt="consent", include_granted_scopes="true"
        )
        # PKCE: コールバック時に必要な code_verifier をセッションに保持
        if getattr(flow, "code_verifier", None):
            st.session_state["oauth_code_verifier"] = flow.code_verifier
        st.warning("Googleアカウントでこのアプリに権限を渡す必要があります。")
        st.link_button("🔐 Googleで認証する", auth_url, use_container_width=True)
        st.stop()
    else:
        col_auth_a, col_auth_b = st.columns([4, 1])
        col_auth_a.success("✅ Googleアカウント認証済み")
        if col_auth_b.button("ログアウト", key="yt_logout"):
            del st.session_state["yt_credentials"]
            st.rerun()

    # ---- 入力フォーム ----
    with st.container(border=True):
        st.markdown("##### ① 案件情報")
        m_number_input2 = st.text_input(
            "M番号",
            value="M0405",
            key="up_m",
            help="STEP 1と同じ番号",
        )
        m_number2 = safe_m_number(m_number_input2)

        st.markdown("##### ② YouTube Video ID")
        video_id_input = st.text_input(
            "Video ID",
            placeholder="例: dQw4w9WgXcQ",
            help="YouTube Studioに動画をアップ後、URLの v= の後ろ11文字 (または youtu.be/ の後ろ)",
            key="up_video_id",
        )

        st.markdown("##### ③ 字幕＆タイトルファイル")
        uploaded_srts = st.file_uploader(
            "21言語SRTファイル（複数選択可）",
            type=["srt"],
            accept_multiple_files=True,
            key="up_srts",
            help="Vrewで書き出した21言語のSRTファイルを全部選択",
        )
        uploaded_titles = st.file_uploader(
            "titles_M####.json",
            type=["json"],
            key="up_titles",
            help="STEP 1で生成したタイトルJSON",
        )

        st.markdown("##### ④ 公開時刻 (JST)")
        col_d, col_t = st.columns(2)
        publish_date = col_d.date_input(
            "公開日",
            value=datetime.now().date() + timedelta(days=7),
        )
        publish_time = col_t.time_input("公開時刻", value=time(9, 0))
        publish_at_iso = (
            datetime.combine(publish_date, publish_time)
            .replace(tzinfo=timezone(timedelta(hours=9)))
            .isoformat()
        )
        st.caption(f"📅 投稿予約: {publish_at_iso}")

        with st.expander("⚙️ 詳細オプション", expanded=False):
            skip_captions = st.checkbox("21言語字幕アップロードをスキップ")
            skip_titles = st.checkbox("21言語のタイトル＆概要欄設定をスキップ")

        upload_clicked = st.button(
            "🚀 YouTubeに投稿予約する",
            type="primary",
            use_container_width=True,
            key="up_btn",
        )

    if upload_clicked:
        tmpdir = None
        try:
            if not video_id_input:
                st.error("❌ Video IDを入力してください")
                st.stop()
            if uploaded_titles is None:
                st.error("❌ titles_M####.json をアップロードしてください")
                st.stop()

            credentials = credentials_from_dict(st.session_state["yt_credentials"])
            yt = YouTubeClient(credentials)
            # トークンが更新された可能性があるので保存し直す
            st.session_state["yt_credentials"] = credentials_to_dict(yt.credentials)

            video_id = video_id_input.strip()
            titles = json.loads(uploaded_titles.getvalue().decode("utf-8"))
            ja_title = titles["ja"]["title"]
            ja_description = titles["ja"]["description"]

            tmpdir = Path(tempfile.mkdtemp(prefix="inaris_"))

            with st.spinner("公開予約を更新中..."):
                yt.schedule_publish(video_id, publish_at_iso)
            st.success(f"📅 公開予約 OK: {publish_at_iso}")

            if not skip_captions:
                if not uploaded_srts:
                    st.error("❌ 21言語SRTファイルをアップロードしてください")
                    st.stop()
                srt_dir = tmpdir / "srts"
                srt_dir.mkdir(exist_ok=True)
                for f in uploaded_srts:
                    (srt_dir / f.name).write_bytes(f.getvalue())

                caption_files = yt.find_caption_files(srt_dir, config["youtube_languages"])
                st.info(
                    f"🌐 検出した言語: {len(caption_files)}/21（{len(uploaded_srts)}ファイル中）"
                )

                progress = st.progress(0.0, text="字幕アップロード中...")
                for i, (lang_code, srt_path) in enumerate(caption_files.items(), 1):
                    progress.progress(
                        i / max(len(caption_files), 1),
                        text=f"字幕アップロード中: {lang_code} ({i}/{len(caption_files)})",
                    )
                    try:
                        yt.upload_caption(video_id, lang_code, srt_path)
                    except Exception as e:
                        st.warning(f"⚠️ {lang_code}: アップロード失敗 - {e}")
                progress.progress(1.0, text="字幕アップ完了")

            if not skip_titles:
                with st.spinner("🌐 21言語のタイトル＆概要欄設定中..."):
                    localizations = {
                        code: {"title": data["title"], "description": data["description"]}
                        for code, data in titles.items()
                    }
                    yt.set_localizations(
                        video_id=video_id,
                        default_language="ja",
                        default_title=ja_title,
                        default_description=ja_description,
                        localizations=localizations,
                    )
                st.success("✅ 21言語のタイトル＆概要欄設定完了")

            st.success(
                f"🎉 すべて完了しました！\n\n"
                f"動画URL: https://youtu.be/{video_id}\n\n"
                f"公開予約: {publish_at_iso}"
            )

        except Exception as e:
            st.exception(e)
        finally:
            if tmpdir and tmpdir.exists():
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)


# ===== フッター =====
st.divider()
st.caption("inaris_youtube_automation • Built for INARIS YouTube production")
