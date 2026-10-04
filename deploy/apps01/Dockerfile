# PaePae を apps01 (ConoHa) で動かすためのイメージ
# Render の「requirements.txt を入れて python run.py」と同じ動きをそのまま再現する
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tokyo \
    PORT=8000

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# /api/version に今動いているコミットを出すため (Render の RENDER_GIT_COMMIT の代わり)
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

# /data は docker-compose で apps01 の /opt/paepae/data を差し込む。
# database.py は /data があればそこを DB と写真の置き場にする (Render の Persistent Disk と同じ扱い)
CMD ["python", "run.py"]
