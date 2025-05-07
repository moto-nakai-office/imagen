# Python 3.10をベースイメージとして使用
FROM python:3.10-slim

# 作業ディレクトリを設定
WORKDIR /app

# 必要なライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# 8080ポートを公開（Cloud Runのデフォルト）
EXPOSE 8080

# サーバーを起動
CMD ["python", "main.py"]
