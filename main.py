import os
import base64
from io import BytesIO
import json
import traceback
from flask import Flask, request, jsonify
from PIL import Image
import vertexai
from vertexai.preview.vision_models import ImageGenerationModel

# Flaskアプリケーションの初期化
app = Flask(__name__)

# Vertex AI初期化
PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("REGION", os.getenv("LOCATION", "us-central1"))
vertexai.init(project=PROJECT_ID, location=LOCATION)

def compress_image(pil_image, max_size=1024 * 1024, max_pixels=1_000_000):
    # 画像サイズをチェックしながらJPEGで圧縮、必要に応じて画像を縮小
    quality = 50
    buffer = BytesIO()
    width, height = pil_image.size

    # まず、画像の総ピクセル数が100万を超えている場合、縮小します
    total_pixels = width * height
    if total_pixels > max_pixels:
        scale_factor = (max_pixels / total_pixels) ** 0.5  # 縮小比率を計算
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)
        
        # どのバージョンのPillowでも動作するリサイズ方法
        pil_image = pil_image.resize((new_width, new_height))

    # 圧縮とリサイズを繰り返し、指定サイズ以下になるまで試行
    while True:
        buffer.seek(0)
        buffer.truncate()

        # 現在のサイズを確認
        pil_image.save(buffer, format="JPEG", quality=quality)
        size = buffer.tell()

        if size <= max_size:
            break  # 目標サイズに収まった場合

        # サイズが大きい場合、クオリティを下げてリサイズ
        quality -= 5
        if quality < 10:  # クオリティが極端に低くならないように制限
            quality = 10

        # 解像度がまだ大きい場合はさらに縮小
        width, height = pil_image.size
        width = int(width * 0.9)
        height = int(height * 0.9)
        
        # どのバージョンのPillowでも動作するリサイズ方法
        pil_image = pil_image.resize((width, height))

    return buffer.getvalue()

def imagen_generate(
    prompt, 
    negative_prompt="", 
    seed=None, 
    aspect_ratio="1:1"
):
    try:
        # Vertex AIのImagen 3.0モデルを初期化
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
        model_version = "imagen-3.0-generate-002"  # モデルバージョンを記録
        
        # 画像生成リクエスト
        generate_response = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            add_watermark=False,
            seed=seed,
            safety_filter_level="block_medium_and_above",
            person_generation="allow_adult"
        )
        
        # 生レスポンスデータの取得（可能な範囲で）
        raw_response = {}
        try:
            # generate_responseオブジェクトから取得できる情報を収集
            raw_response = {
                "image_count": len(generate_response),
                # その他の取得可能なメタデータがあれば追加
            }
        except Exception as e:
            raw_response = {"error": f"生レスポンス取得エラー: {str(e)}"}
        
        image_list = []
        for index, result in enumerate(generate_response):
            # PIL Imageオブジェクトを取得
            pil_image = generate_response[index]._pil_image

            # 画像を2MB以下に圧縮してバイト列を取得
            compressed_image_bytes = compress_image(pil_image)

            # base64エンコード
            img_str = base64.b64encode(compressed_image_bytes).decode("utf-8")

            # エンコードされた画像をリストに追加
            image_list.append(img_str)

        # モデルバージョンと生レスポンスを含めて返却
        return image_list, None, model_version, raw_response
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"エラー詳細: {error_details}", flush=True)
        return None, str(e), None, None

@app.route("/generate", methods=["POST"])
def generate():
    try:
        # リクエストから必要なパラメータを取得
        data = request.get_json()
        
        # バリデーション
        if not data or "prompt" not in data or not data["prompt"]:
            return jsonify({"error": "プロンプトは必須です"}), 400
            
        prompt = data["prompt"]
        negative_prompt = data.get("negative_prompt", "")
        seed = data.get("seed", None)
        aspect_ratio = data.get("aspect_ratio", "3:4")
        
        # 画像生成（修正版関数を呼び出し）
        images, error, model_version, raw_response = imagen_generate(prompt, negative_prompt, seed, aspect_ratio)
        
        if error:
            return jsonify({"error": error}), 500
            
        # 結果を返却（拡張バージョン）
        return jsonify({
            "status": "success",
            "data": {
                "images": images,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "aspect_ratio": aspect_ratio,
                "model_version": model_version,  # モデルバージョンを追加
                "raw_response": raw_response     # 生レスポンス情報を追加
            }
        })
        
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"エラー詳細: {error_details}", flush=True)
        return jsonify({"error": str(e), "details": error_details}), 500

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "imagen-api"})

@app.route("/debug", methods=["GET"])
def debug():
    try:
        # Vertex AIのバージョン情報
        import vertexai
        vertexai_version = getattr(vertexai, "__version__", "不明")
        
        # ImageGenerationModelの情報
        from vertexai.preview.vision_models import ImageGenerationModel
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
        
        # メソッドのシグネチャを調査
        import inspect
        method_signature = str(inspect.signature(model.generate_images))
        
        return jsonify({
            "status": "success",
            "vertexai_version": vertexai_version,
            "method_signature": method_signature,
            "environment": {k: v for k, v in os.environ.items() if k.startswith("GOOGLE_")}
        })
    except Exception as e:
        error_details = traceback.format_exc()
        return jsonify({"error": str(e), "traceback": error_details})

@app.route("/debug/params", methods=["GET"])
def debug_params():
    try:
        # Vertex AIのバージョン情報
        import inspect
        vertexai_version = getattr(vertexai, "__version__", "不明")
        
        # ImageGenerationModelの初期化
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
        
        # generate_imagesメソッドのシグネチャを取得
        method_signature = inspect.signature(model.generate_images)
        
        # パラメータ情報を取得
        params_info = {}
        for param_name, param in method_signature.parameters.items():
            params_info[param_name] = {
                "name": param_name,
                "default": str(param.default) if param.default is not inspect.Parameter.empty else "必須",
                "kind": str(param.kind),
                "annotation": str(param.annotation) if param.annotation is not inspect.Parameter.empty else "不明"
            }
        
        # docstringからパラメータ情報を抽出
        docstring = model.generate_images.__doc__ or "ドキュメント文字列なし"
        
        # モジュール情報の取得
        module_info = {
            "module_name": model.__class__.__module__,
            "model_class": model.__class__.__name__
        }
        
        # ソースコードの位置を取得（可能な場合）
        try:
            source_info = inspect.getfile(model.__class__)
        except:
            source_info = "取得不可"
        
        return jsonify({
            "status": "success",
            "vertexai_version": vertexai_version,
            "method_signature": str(method_signature),
            "parameters": params_info,
            "docstring": docstring,
            "module_info": module_info,
            "source_location": source_info
        })
    except Exception as e:
        error_details = traceback.format_exc()
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": error_details
        }), 500

@app.route("/debug/model", methods=["GET"])
def debug_model():
    try:
        # モデルのインスタンス化
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
        
        # クラスのメソッド一覧を取得
        methods = {}
        for method_name in dir(model):
            if not method_name.startswith("_"):  # 非プライベートメソッドのみ
                method = getattr(model, method_name)
                if callable(method):
                    try:
                        methods[method_name] = {
                            "signature": str(inspect.signature(method)),
                            "doc": inspect.getdoc(method) or "ドキュメントなし"
                        }
                    except:
                        methods[method_name] = {"error": "シグネチャ取得不可"}
        
        # クラスの属性を取得
        attributes = {}
        for attr_name in dir(model):
            if not attr_name.startswith("_") and attr_name not in methods:
                try:
                    attr_value = getattr(model, attr_name)
                    attributes[attr_name] = str(type(attr_value))
                except:
                    attributes[attr_name] = "取得不可"
        
        return jsonify({
            "status": "success",
            "class_name": model.__class__.__name__,
            "methods": methods,
            "attributes": attributes
        })
    except Exception as e:
        error_details = traceback.format_exc()
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": error_details
        }), 500

@app.route("/debug/test-param", methods=["POST"])
def test_param():
    try:
        # リクエストからデータを取得
        data = request.get_json()
        prompt = data.get("prompt", "富士山")
        param_name = data.get("param_name")
        param_value = data.get("param_value")
        
        # モデルをインスタンス化
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
        
        # 基本パラメータ
        params = {
            "prompt": prompt,
            "number_of_images": 1
        }
        
        # テスト対象のパラメータを追加
        if param_name and param_value is not None:
            params[param_name] = param_value
        
        # 結果
        result_info = {
            "tested_param": param_name,
            "param_value": param_value,
            "params_used": params
        }
            
        # テスト実行（実際の画像生成はスキップ可能）
        if data.get("execute", False):
            try:
                response = model.generate_images(**params)
                result_info["execution"] = "成功"
            except Exception as exec_error:
                result_info["execution"] = "失敗"
                result_info["execution_error"] = str(exec_error)
        
        return jsonify({
            "status": "success",
            "result": result_info
        })
    except Exception as e:
        error_details = traceback.format_exc()
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": error_details
        }), 500


if __name__ == "__main__":
    # 環境変数PORTを明示的に取得
    port = int(os.environ.get('PORT', 8080))
    # ホストは必ず'0.0.0.0'に設定
    app.run(host='0.0.0.0', port=port, debug=False)
