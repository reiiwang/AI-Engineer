# WeKnora Docker 指令筆記（macOS）

> 日期：2026-10-19 · 適用：WeKnora v0.8.2 標準版（`docker compose`，ParadeDB）
> 以下指令都在 WeKnora repo 目錄執行：`cd ~/Projects/AI-Engineer/WeKnora`

---

## 1. 第一次安裝

```bash
brew install --cask docker   # 安裝 Docker Desktop
open -a Docker               # 一定要開一次，compose plugin 才會連結好
docker compose version       # 有版本號就代表可以用
```

如果開過 Docker Desktop 還是出現 `docker: unknown command: docker compose`，就手動連結 plugin：

```bash
mkdir -p ~/.docker/cli-plugins
ln -sf /Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose ~/.docker/cli-plugins/docker-compose
```

## 2. 啟動

```bash
cp .env.example .env     # 第一次才需要，依註解修改
docker compose pull      # 下載映像檔
docker compose up -d     # 在背景啟動
```

啟動後打開 http://localhost 。

## 3. 查看狀態與除錯

```bash
docker compose ps                                       # 各容器狀態，是否 healthy
docker compose logs -f app | grep -v "method=GET"       # 即時看後端 log，濾掉前端輪詢
docker compose logs app --since 10m | grep -E "ERROR|WARN"   # 最近 10 分鐘的錯誤
docker compose logs -f docreader                        # 卡在「解析中」時看這個
docker compose restart app                              # 改了 config/config.yaml 後重啟
```

常見訊息：

| log 訊息 | 原因 | 處理 |
|---|---|---|
| `Unknown parameter: 'chat_template_kwargs'` | OpenAI 模型用「通用 OpenAI 相容」廠商加入 | 模型的廠商改成 **OpenAI** |
| `summary model output was truncated at the completion budget` | 推理模型（如 `gpt-5-mini`）把 1024 token 的摘要上限用完 | `config/config.yaml` 的 `conversation.summary.max_completion_tokens` 調高（例如 4096）後重啟 app，或摘要改用非推理模型 |
| `Vector/keyword indexing disabled for KB` | 知識庫沒開索引 | 在知識庫設定打開索引並選 embedding 模型 |

## 4. 直接查資料庫

```bash
# 進入 psql
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

# 直接跑一行 SQL，例如依類型統計 wiki 頁面
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT page_type, count(*) FROM wiki_pages WHERE deleted_at IS NULL GROUP BY 1;"'
```

會用到的表：`wiki_pages`（頁面，`folder_id` 指向分類）、`wiki_folders`（分類資料夾樹）。

## 5. 停止（保留資料）

```bash
docker compose stop      # 只停止容器，什麼都不刪（最保險）
docker compose start     # 重新啟動

docker compose down      # 刪除容器和網路，volume 保留
docker compose up -d     # 重新建立容器
```

資料存在這些 volume，`stop` 和 `down` 都不會刪：

| Volume | 內容 |
|---|---|
| `weknora_postgres-data` | 知識庫、文件、chunk、向量、wiki 頁面和資料夾 |
| `weknora_data-files` | 上傳的原始檔案 |
| `weknora_docreader-tmp` | 解析暫存檔 |

Redis 沒有掛 volume，裡面是任務佇列。`down` 會清掉還沒跑完的任務，所以有文件還在處理時，用 `stop`。

## 6. 完全刪除（無法復原）

```bash
docker compose down -v               # 刪容器、網路和所有 volume（資料全部消失）
docker compose down -v --rmi all     # 連映像檔一起刪，下次要重新 pull
```

`make clean-db` 也會刪掉 postgres 的 volume，不要誤用。

確認有沒有刪乾淨：

```bash
docker ps -a | grep -i weknora
docker volume ls | grep -i weknora
docker images | grep -i -E "weknora|paradedb|redis"
```

三個指令都沒有輸出，就代表刪乾淨了。
