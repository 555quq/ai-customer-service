#!/bin/bash
# 后台重试拉取 postgres 和 chatwoot 镜像（轮换国内镜像源，成功自动 re-tag）
# 用法: bash scripts/docker_retry_pull.sh
SOURCES=("docker.m.daocloud.io" "docker.1ms.run" "docker.xuanyuan.me" "docker.1panel.live")
LOG=/tmp/docker_retry.log
echo "[$(date +%T)] ==== 后台镜像重试开始 ====" >> "$LOG"

# 确保 Docker daemon 在线（断开则重启 Docker Desktop 并等待）
ensure_docker() {
  if ! docker info >/dev/null 2>&1; then
    echo "[$(date +%T)] Docker daemon 断开，尝试重启 Docker Desktop..." >> "$LOG"
    cmd.exe //c start "" "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe" 2>/dev/null
    for j in $(seq 1 36); do
      sleep 5
      if docker info >/dev/null 2>&1; then
        echo "[$(date +%T)] Docker daemon 已恢复" >> "$LOG"
        return 0
      fi
    done
    echo "[$(date +%T)] Docker 恢复等待超时" >> "$LOG"
  fi
  return 0
}

pull_and_tag() {
  local target="$1"   # 源内路径，如 library/postgres:14-alpine
  local final="$2"    # 最终 tag，如 postgres:14-alpine
  echo "[$(date +%T)] 开始拉取 $final" >> "$LOG"
  for src in "${SOURCES[@]}"; do
    ensure_docker
    if docker image inspect "$final" >/dev/null 2>&1; then
      echo "[$(date +%T)] $final 已就位，跳过" >> "$LOG"
      return 0
    fi
    echo "[$(date +%T)]   尝试源: $src/$target" >> "$LOG"
    if timeout 400 docker pull "$src/$target" >> "$LOG" 2>&1; then
      docker tag "$src/$target" "$final" 2>>"$LOG"
      echo "[$(date +%T)] ✅ $final 拉取成功 (via $src)" >> "$LOG"
      return 0
    fi
    echo "[$(date +%T)]   源 $src 失败/超时，换下一个" >> "$LOG"
  done
  echo "[$(date +%T)] $final 本轮全部源失败，60s 后重试" >> "$LOG"
  return 1
}

# 循环直到 postgres 就位
while ! docker image inspect postgres:14.23-alpine >/dev/null 2>&1; do
  pull_and_tag "library/postgres:14.23-alpine" "postgres:14.23-alpine" || sleep 60
done

# 循环直到 chatwoot 就位
while ! docker image inspect chatwoot/chatwoot:v3.11.0 >/dev/null 2>&1; do
  pull_and_tag "chatwoot/chatwoot:v3.11.0" "chatwoot/chatwoot:v3.11.0" || sleep 60
done

echo "[$(date +%T)] ==== 全部镜像就位 ====" >> "$LOG"
