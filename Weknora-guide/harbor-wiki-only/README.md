# 用公司 Harbor 部署 WeKnora（只用 wiki）

> 日期：2026-10-19 · 適用：WeKnora v0.8.2 · 目標機器：公司 Linux
> 用途：手動輸入 txt 內容，知識庫只勾 wiki、不勾 RAG，看 wiki 建出來的結果
> **狀態：尚未實測。**

只跑 4 個服務：`frontend`、`app`、`postgres`、`redis`。沒有 docreader，也不需要 embedding 模型。映像檔都從 Harbor 的 Docker Hub 代理拉，不用自己 build。

---

## 1. 先確認 Harbor 拉得到映像檔

找 IT 問 Docker Hub 代理專案的名稱，或到 Harbor 網頁上找類型是 **Proxy Cache** 的專案。下面假設是 `harbor.mycompany.com/dockerhub`。

```bash
docker login harbor.mycompany.com

docker pull harbor.mycompany.com/dockerhub/wechatopenai/weknora-app:v0.8.2
docker pull harbor.mycompany.com/dockerhub/wechatopenai/weknora-ui:v0.8.2
docker pull harbor.mycompany.com/dockerhub/paradedb/paradedb:v0.25.11-pg17
docker pull harbor.mycompany.com/dockerhub/library/redis:7.0-alpine
```

- **redis 要加 `library/`**：Docker Hub 的官方映像檔透過 Harbor 代理時都是這個路徑。
- **四個都拉得到**，就繼續第 2 步。
- **拉不到**，把錯誤訊息給 IT 看。常見原因是沒有代理專案、沒有權限，或專案只同步特定映像檔，需要申請加入。
- 如果 `v0.8.2` 這個 tag 不存在，到 Harbor 或 Docker Hub 上看實際有哪些 tag，再改 `.env` 裡的 `WEKNORA_VERSION`。

## 2. 準備設定檔

這個資料夾裡只有兩個檔案是一定要的：`docker-compose.yml` 和 `.env`。

```bash
cp .env.example .env
```

編輯 `.env`：

| 項目 | 怎麼填 |
|---|---|
| `REGISTRY` | 第 1 步確認的 Harbor 路徑，例如 `harbor.mycompany.com/dockerhub` |
| `DB_PASSWORD`、`REDIS_PASSWORD` | 自己訂 |
| `JWT_SECRET`、`SYSTEM_SIGNING_KEY` | `openssl rand -hex 32` |
| `SYSTEM_AES_KEY` | `openssl rand -hex 16`（**必須剛好 32 個字元**） |
| `SSRF_WHITELIST` | 公司 LLM API 的網域，例如 `llm.mycompany.com`。有多個就用逗號分開 |

```bash
docker compose config --images   # 確認四個映像檔路徑都對
```

## 3. 啟動

```bash
docker compose up -d
docker compose ps                 # 等 app 和 postgres 都變成 healthy
docker compose logs -f app | grep -v "method=GET"
```

然後打開 `http://<機器 IP>`。

## 4. 在 UI 上設定

1. **加入 chat 模型**：設定 → 模型，填入公司 LLM API。
   - 如果是 OpenAI 官方或相容 Azure OpenAI 的服務，廠商選對應的那個。
   - 如果是 vLLM、SGLang 這類自架的，才選「通用 OpenAI 相容」。
   - 廠商選錯的話，可能出現 `Unknown parameter: 'chat_template_kwargs'`，見 [`../docker-commands.md`](../docker-commands.md) 第 3 節。
2. **建立知識庫**：只勾 **wiki**，不勾 RAG。不需要選 embedding 模型。
3. **新增文件**：選手動輸入，貼上文字內容。
4. 看 wiki 頁面和資料夾有沒有長出來。

## 5. 可能遇到的問題

| 症狀 | 處理 |
|---|---|
| 卡在 summary，log 出現 `truncated at the completion budget` | 公司模型是推理模型時，摘要的 1024 token 上限不夠用，見下面「修改 config.yaml」 |
| log 出現連線被拒、`not in whitelist` 之類的訊息 | `SSRF_WHITELIST` 漏了 LLM API 的位址 |
| 上傳 PDF、Word 失敗 | 正常，沒有 docreader，只支援 md、txt、csv、json 和手動輸入 |
| 拉映像檔時 `manifest unknown` | tag 不存在，或 Harbor 路徑錯了 |

### 修改 config.yaml

`app` 映像檔裡已經有預設的 `config.yaml`，所以平常不用掛載。真的要改的話，先從映像檔裡複製一份出來：

```bash
mkdir -p config
docker compose run --rm --no-deps --entrypoint cat app /app/config/config.yaml > config/config.yaml
```

改好之後（例如把 `conversation.summary.max_completion_tokens` 改成 `4096`），把 `docker-compose.yml` 裡 `app` 的這一行取消註解：

```yaml
      - ./config/config.yaml:/app/config/config.yaml
```

```bash
docker compose up -d app
```

## 6. 停止與刪除

和 [`../docker-commands.md`](../docker-commands.md) 第 5、6 節一樣：`docker compose stop` 會保留資料，`docker compose down -v` 會刪掉所有資料。

---

## 跟官方 docker-compose.yml 的差異

| 項目 | 官方 | 這份 |
|---|---|---|
| 服務 | frontend、app、docreader、postgres、redis（加上很多 profile 才會開的服務） | frontend、app、postgres、redis |
| 映像檔來源 | Docker Hub | `${REGISTRY}`（Harbor） |
| 版本 | `latest` | 固定 `v0.8.2` |
| `build:` 區塊 | 有 | 拿掉了，只拉現成的映像檔 |
| `DOCREADER_ADDR` | `docreader:50051` | 空字串（未連線） |
| `config.yaml` | 掛載 repo 裡的檔案 | 預設用映像檔內建的 |
| `environment:` 區塊 | 列了很多選用設定 | 只留必要的，其他都讀 `.env` |

最後一項是最可能出問題的地方。我精簡時假設 app 對沒有列出的設定都有內建預設值。如果啟動時 log 抱怨缺少某個環境變數，就從官方 `docker-compose.yml` 的 `app.environment` 找到那一項，補進 `.env`。
