#!/bin/sh
# apps01 で PaePae を最新の main に入れ替える
#   ssh -i ~/.ssh/conoha_apps root@100.83.40.43 'sh /opt/paepae/app/deploy/apps01/deploy.sh'
# Render の「GitHub に push したら自動デプロイ」の代わり。今は手で (または Claude が) 流す
set -eu
cd /opt/paepae
git -C app pull --ff-only
cp app/deploy/apps01/docker-compose.yml app/deploy/apps01/serve.json .
GIT_COMMIT=$(git -C app rev-parse HEAD) docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
docker compose ps
