import os
import base64
from io import BytesIO
import json
from flask import Flask, request, jsonify
from PIL import Image
import vertexai
from vertexai.preview.vision_models import ImageGenerationModel

# Flaskアプリケーションの初期化
app = Flask(__name__)

# Vertex AI初期化
PROJECT_ID = os.environ.get("PROJECT_ID", "your-project-id")
LOCATION = os.environ.get("LOCATION", "us-central1")
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
        pil_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

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
        pil_image = pil_image.resize((width, height), Image.Resampling.LANCZOS)

    return buffer.getvalue()

def imagen_generate(prompt, negative_prompt="", seed=None, aspect_ratio="3:4"):
    try:
        # Vertex AIのImagen 3.0モデルを初期化
        model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
        
        # 画像生成リクエスト
        generate_response = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            negative_prompt=negative_prompt,
            # aspect_ratio=aspect_ratio,
            # language="en",
            # add_watermark=False,
            # seed=seed,
            safety_filter_level="block_some",
            person_generation="allow_adult",
        )
        
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

        return image_list, None
    except Exception as e:
        return None, str(e)

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
        
        # 画像生成
        images, error = imagen_generate(prompt, negative_prompt, seed, aspect_ratio)
        
        if error:
            return jsonify({"error": error}), 500
            
        # 結果を返却
        return jsonify({
            "status": "success",
            "data": {
                "images": images,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "aspect_ratio": aspect_ratio
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "imagen-api"})

if __name__ == "__main__":
    # Cloud Runのデフォルトポートを使用
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
