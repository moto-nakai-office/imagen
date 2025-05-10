import streamlit as st
import requests
import base64
from io import BytesIO
from PIL import Image
import json
import time
import os
import uuid
from datetime import datetime
from google.cloud import storage
from google.cloud import bigquery

# ページ設定
st.set_page_config(
    page_title="Gemini画像生成",
    page_icon="🎨",
    layout="wide",
)

# GCSに画像を保存する関数
def save_image_to_gcs(image_data, bucket_name, prompt):
    """Base64画像データをGCSに保存"""
    try:
        # ファイル名を生成（一意のID + タイムスタンプ + プロンプトの短縮版）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        # プロンプトからファイル名用の文字列を生成（短くして特殊文字を除去）
        prompt_slug = "".join(c for c in prompt[:30] if c.isalnum() or c.isspace()).strip().replace(" ", "_")
        if not prompt_slug:
            prompt_slug = "image"
            
        filename = f"{timestamp}_{unique_id}_{prompt_slug}.png"
        
        # GCSクライアントを初期化
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(f"gemini_images/{filename}")
        
        # 画像データをPNGとして保存
        img = Image.open(BytesIO(base64.b64decode(image_data)))
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # GCSにアップロード
        blob.upload_from_file(img_byte_arr, content_type='image/png')
        
        # 公開URLを生成
        image_url = f"gs://{bucket_name}/gemini_images/{filename}"
        public_url = f"https://storage.googleapis.com/{bucket_name}/gemini_images/{filename}"
        
        return {
            "success": True,
            "gcs_uri": image_url,
            "public_url": public_url,
            "filename": filename
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# BigQueryにログを保存する関数
def log_to_bigquery(data, project_id, dataset_id, table_id):
    """生成情報をBigQueryに保存"""
    try:
        # BigQueryクライアントを初期化
        bq_client = bigquery.Client(project=project_id)
        table_ref = f"{project_id}.{dataset_id}.{table_id}"
        
        # 行を挿入
        errors = bq_client.insert_rows_json(
            table_ref,
            [data]
        )
        
        if errors:
            return {"success": False, "errors": errors}
        else:
            return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# タイトルとヘッダー
st.title("Gemini AI 画像生成アプリ")
st.markdown("Gemini 2.0を使って、テキストプロンプトから画像を生成できます。")

# サイドバーにAPI設定
with st.sidebar:
    st.header("API設定")
    api_url = st.text_input(
        "API URL", 
        value="https://gemini-api-xxxxxx-uc.a.run.app/generate-image",
        help="画像生成APIのエンドポイントURL"
    )
    
    # API情報取得用エンドポイント
    api_info_url = api_url.rsplit('/', 1)[0] + "/info" if "/" in api_url else api_url + "/info"
    
    # 詳細設定
    st.markdown("---")
    st.header("詳細設定")
    aspect_ratio = st.selectbox(
        "アスペクト比",
        options=["16:9", "1:1", "3:4", "4:3", "9:16"],
        index=0,
        help="生成する画像のアスペクト比"
    )
    
    seed = st.number_input(
        "シード値",
        min_value=0,
        max_value=1000000,
        value=0,
        help="同じ結果を再現するためのシード値（0はランダム）"
    )
    
    # ログ設定
    st.markdown("---")
    st.header("ログ設定")
    
    logging_enabled = st.toggle("ログ記録を有効にする", value=False)
    
    if logging_enabled:
        # GCS設定
        gcs_bucket = st.text_input(
            "GCSバケット名",
            value="your-bucket-name",
            help="生成画像を保存するGCSバケット"
        )
        
        # BigQuery設定
        bq_expander = st.expander("BigQuery設定", expanded=True)
        with bq_expander:
            bq_project = st.text_input("プロジェクトID", value="your-project-id")
            bq_dataset = st.text_input("データセットID", value="gemini_logs")
            bq_table = st.text_input("テーブル名", value="image_generation_logs")
            
            st.info("""
            BigQueryテーブルは以下のスキーマが必要です:
            - timestamp: TIMESTAMP
            - prompt: STRING
            - negative_prompt: STRING
            - model_version: STRING
            - aspect_ratio: STRING
            - seed: INTEGER
            - gcs_uri: STRING
            - public_url: STRING
            """)
    
    # デバッグモード
    st.markdown("---")
    debug_mode = st.checkbox("デバッグモード", value=True, help="APIレスポンスの詳細を表示します")
    
    st.markdown("---")
    st.header("About")
    st.markdown("このアプリはVertex AI Gemini 2.0を使用した画像生成APIと連携しています。")

# APIからモデル情報を取得する試み
@st.cache_data(ttl=3600)  # 1時間キャッシュ
def get_api_info(url):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        return {"error": f"ステータスコード: {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

# モデル情報の取得を試みる
try:
    api_info = get_api_info(api_info_url)
    if "error" not in api_info and "model_version" in api_info:
        model_version = api_info["model_version"]
    else:
        model_version = "unknown"  # デフォルト値
except:
    model_version = "unknown"  # デフォルト値

# メインコンテンツ - 2カラムレイアウト
col1, col2 = st.columns([1, 1])

with col1:
    st.header("プロンプト入力")
    
    # プロンプト入力
    prompt = st.text_area(
        "画像生成プロンプト",
        value="富士山と桜の風景、春の朝",
        height=150,
        help="生成したい画像の説明を入力してください"
    )
    
    # ネガティブプロンプト
    negative_prompt = st.text_area(
        "ネガティブプロンプト（任意）",
        value="",
        height=100,
        help="画像に含めたくない要素を指定します"
    )
    
    # 生成ボタン
    if st.button("画像を生成", type="primary", use_container_width=True):
        with st.spinner("画像を生成中..."):
            try:
                # リクエスト開始時間
                start_time = time.time()
                
                # APIリクエストデータ
                request_data = {
                    "prompt": prompt,
                    "negative_prompt": negative_prompt
                }
                
                # シード値が指定されている場合
                if seed > 0:
                    request_data["seed"] = seed
                
                # アスペクト比を追加
                if aspect_ratio:
                    request_data["aspect_ratio"] = aspect_ratio
                
                # デバッグ表示
                if debug_mode:
                    st.subheader("リクエスト内容")
                    st.json(request_data)
                
                # APIリクエスト
                response = requests.post(
                    api_url,
                    json=request_data,
                    headers={"Content-Type": "application/json"},
                    timeout=120  # タイムアウトを長めに設定
                )
                
                # 処理時間
                process_time = time.time() - start_time
                
                # デバッグ情報
                if debug_mode:
                    st.subheader("APIレスポンス詳細")
                    debug_container = st.container()
                    with debug_container:
                        col_status, col_time = st.columns(2)
                        with col_status:
                            st.metric("ステータスコード", response.status_code)
                        with col_time:
                            st.metric("処理時間", f"{process_time:.2f}秒")
                        
                        st.markdown("#### レスポンスヘッダー")
                        st.json(dict(response.headers))
                        
                        st.markdown("#### レスポンス内容")
                        try:
                            resp_json = response.json()
                            # データ量が多い場合は画像データを省略して表示
                            if "data" in resp_json and "images" in resp_json["data"] and resp_json["data"]["images"]:
                                display_json = resp_json.copy()
                                images = display_json["data"]["images"]
                                # 各画像を省略表示に置き換え
                                display_json["data"]["images"] = [
                                    f"[BASE64エンコード画像データ: {len(img)}文字]" for img in images
                                ]
                                st.json(display_json)
                            else:
                                st.json(resp_json)
                            
                            # レスポンス構造の確認
                            st.text(f"レスポンスのキー: {list(resp_json.keys())}")
                            if "data" in resp_json:
                                st.text(f"data内のキー: {list(resp_json['data'].keys())}")
                                if "images" in resp_json["data"]:
                                    st.text(f"images配列の長さ: {len(resp_json['data']['images'])}")
                                
                                # model_versionがレスポンスに含まれている場合は取得
                                if "model_version" in resp_json["data"]:
                                    model_version = resp_json["data"]["model_version"]
                                elif "model" in resp_json["data"]:
                                    model_version = resp_json["data"]["model"]
                        except:
                            st.text("JSONではないレスポンス:")
                            st.text(response.text[:1000])  # 長すぎる場合は一部のみ表示
                
                # レスポンス確認
                if response.status_code == 200:
                    result = response.json()
                    
                    # model_versionの取得を試みる
                    if "data" in result:
                        if "model_version" in result["data"]:
                            model_version = result["data"]["model_version"]
                        elif "model" in result["data"]:
                            model_version = result["data"]["model"]
                    
                    # 正しいパスから画像データを取得
                    if ("status" in result and result["status"] == "success" and 
                            "data" in result and "images" in result["data"] and 
                            result["data"]["images"]):
                        # 画像データを保存
                        image_data = result["data"]["images"][0]
                        st.session_state.generated_image = image_data
                        st.session_state.last_prompt = prompt
                        st.session_state.last_negative_prompt = negative_prompt
                        st.session_state.last_aspect_ratio = aspect_ratio
                        st.session_state.last_seed = seed if seed > 0 else None
                        st.session_state.model_version = model_version
                        st.success("画像が生成されました！")
                        
                        # ログ記録が有効な場合、GCSとBigQueryに保存
                        if logging_enabled:
                            log_section = st.container()
                            with log_section:
                                st.markdown("#### ログ記録")
                                
                                # GCSに画像を保存
                                with st.spinner("画像をGCSに保存中..."):
                                    gcs_result = save_image_to_gcs(
                                        image_data, 
                                        gcs_bucket, 
                                        prompt
                                    )
                                    
                                    if gcs_result["success"]:
                                        st.session_state.gcs_uri = gcs_result["gcs_uri"]
                                        st.session_state.public_url = gcs_result["public_url"]
                                        st.success(f"GCSに画像を保存しました: {gcs_result['filename']}")
                                        
                                        # BigQueryにログを保存
                                        with st.spinner("BigQueryにログを記録中..."):
                                            log_data = {
                                                "timestamp": datetime.now().isoformat(),
                                                "prompt": prompt,
                                                "negative_prompt": negative_prompt,
                                                "model_version": model_version,
                                                "aspect_ratio": aspect_ratio,
                                                "seed": seed if seed > 0 else None,
                                                "gcs_uri": gcs_result["gcs_uri"],
                                                "public_url": gcs_result["public_url"]
                                            }
                                            
                                            bq_result = log_to_bigquery(
                                                log_data,
                                                bq_project,
                                                bq_dataset,
                                                bq_table
                                            )
                                            
                                            if bq_result["success"]:
                                                st.success("BigQueryにログを記録しました")
                                            else:
                                                st.error(f"BigQueryへの記録に失敗: {bq_result.get('error', bq_result.get('errors', '不明なエラー'))}")
                                    else:
                                        st.error(f"GCSへの保存に失敗: {gcs_result.get('error', '不明なエラー')}")
                    else:
                        # 構造を表示して問題をデバッグ
                        st.error("画像データが正しい形式で返されていません")
                        st.write("レスポンス構造:", result.keys())
                        if "data" in result:
                            st.write("data内の構造:", result["data"].keys())
                            if "images" in result["data"]:
                                st.write("images配列の長さ:", len(result["data"]["images"]))
                else:
                    error_message = f"エラー: {response.status_code}"
                    try:
                        error_detail = response.json().get("error", "詳細不明")
                        error_message += f" - {error_detail}"
                    except:
                        error_message += f" - レスポンス: {response.text[:200]}..."
                    st.error(error_message)
            except Exception as e:
                st.error(f"リクエスト中にエラーが発生しました: {str(e)}")
                import traceback
                if debug_mode:
                    st.code(traceback.format_exc())
    
    # 履歴表示
    if "generated_image" in st.session_state:
        st.markdown("---")
        st.subheader("生成設定")
        
        # 設定情報を表示
        settings_container = st.container()
        with settings_container:
            st.markdown(f"**プロンプト**: {st.session_state.last_prompt}")
            
            if st.session_state.last_negative_prompt:
                st.markdown(f"**ネガティブプロンプト**: {st.session_state.last_negative_prompt}")
            
            # モデル情報と生成設定を表示
            col_model, col_aspect, col_seed = st.columns(3)
            with col_model:
                st.markdown(f"**モデル**: {st.session_state.model_version}")
            with col_aspect:
                st.markdown(f"**アスペクト比**: {st.session_state.last_aspect_ratio}")
            with col_seed:
                seed_value = st.session_state.last_seed if hasattr(st.session_state, 'last_seed') else "ランダム"
                st.markdown(f"**シード値**: {seed_value}")
            
            # GCS情報表示
            if hasattr(st.session_state, 'public_url'):
                st.markdown("---")
                st.markdown(f"**GCS URI**: `{st.session_state.gcs_uri}`")
                st.markdown(f"**公開URL**: [画像リンク]({st.session_state.public_url})")

# 生成画像表示エリア
with col2:
    st.header("生成画像")
    if "generated_image" in st.session_state:
        try:
            # Base64デコードして画像を表示
            image_data = base64.b64decode(st.session_state.generated_image)
            img = Image.open(BytesIO(image_data))
            st.image(img, use_column_width=True)
            
            # モデル情報を表示
            if hasattr(st.session_state, 'model_version'):
                st.caption(f"モデル: {st.session_state.model_version}")
            
            # ダウンロードボタン
            buf = BytesIO()
            img.save(buf, format="PNG")
            btn = st.download_button(
                label="画像をダウンロード",
                data=buf.getvalue(),
                file_name="generated_image.png",
                mime="image/png",
                use_container_width=True
            )
        except Exception as img_error:
            st.error(f"画像の表示中にエラーが発生しました: {str(img_error)}")
            
            # デバッグ情報
            if debug_mode:
                st.text(f"画像データの先頭部分: {st.session_state.generated_image[:50]}...")
                st.text(f"画像データの長さ: {len(st.session_state.generated_image)}")
    else:
        st.info("プロンプトを入力して「画像を生成」ボタンをクリックしてください")

# フッター
st.markdown("---")
st.markdown("Powered by Google Vertex AI Gemini 2.0")

# Cloud Run対応のポート設定
if __name__ == "__main__":
    # 環境変数PORTの値を取得（デフォルトは8501）
    port = int(os.environ.get("PORT", 8501))
    # デバッグ情報としてポート設定を表示
    print(f"Configured to listen on port {port}")
    
    # StreamlitをCloud Run互換モードで起動
    import sys
    import subprocess
    cmd = [
        "streamlit", 
        "run", 
        sys.argv[0],
        "--server.port", str(port),
        "--server.address", "0.0.0.0"
    ]
    subprocess.call(cmd)
