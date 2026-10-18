# WeKnora 公司內網（離線）部署筆記

> 日期：2026-10-19 · 適用：WeKnora v0.8.2 標準版（`docker compose`）
> 前提：公司機器不能連外網。所有引進內網的軟體，都要走公司允許的管道。
> 基本 Docker 指令見 [`docker-commands.md`](docker-commands.md)。

---

## 1. 結論先講

| 階段 | 能不能完全不連網 | 怎麼做 |
|---|---|---|
| **執行** | 可以 | 模型放在內網，加上開啟白名單出站模式（見第 4 節） |
| **build / 安裝** | 不行，程式依賴總要有來源 | 改用公司內部鏡像，或請 IT 審核後引進映像檔（見第 3 節） |

如果只處理純文字（md、txt、csv、json），可以拿掉 docreader，要準備的東西會少很多（見第 5 節）。

> **目前採用的做法（2026-10-19）**：公司不能帶入壓縮包或映像檔，但有 Harbor。所以改成透過 Harbor 的 Docker Hub 代理，直接拉官方已經 build 好的映像檔，只用 wiki 功能，不需要 docreader 和 embedding。步驟和設定檔在 [`harbor-wiki-only/`](harbor-wiki-only/README.md)。

---

## 2. 為什麼不能在離線機器上自己 build

三個要自己 build 的映像檔都需要連網，連最單純的前端也一樣。

### 2.1 `weknora-ui`（`frontend/Dockerfile`）

前端是相對簡單的一個，只有兩類需求：

| 需求 | 內容 | 能不能換成內部來源 |
|---|---|---|
| 基底映像檔 | `node:24-bookworm-slim`（build 階段）、`nginx:1.30.3-alpine`（執行階段） | 可以，從內部 registry 拉 |
| npm 套件 | `npm ci`（第 39-42 行） | 可以，`--build-arg NPM_REGISTRY=<內部 npm registry>` |

只要公司有內部的 Docker registry 和 npm registry，前端就能在內網 build。

### 2.2 `weknora-app`（`docker/Dockerfile.app`）

這是需要連網最多的一個，分成三個 build 階段：

**階段 1：browserskill（第 1-24 行，一定會執行，沒有開關可以關掉）**

| 需求 | 內容 |
|---|---|
| 基底映像檔 | `node:24-bookworm-slim` |
| 系統套件 | `apt-get install` git、cmake、build-essential… |
| Rust 工具鏈 | `curl https://sh.rustup.rs`（第 20 行） |
| 原始碼 | `git clone https://github.com/Tencent/BrowserSkill.git`（`scripts/build_browserskill.sh:35`） |
| 套件 | `npx pnpm@10.17.0 install`（npm）、`cargo build`（crates.io） |

**階段 2：Go builder（第 27-96 行）**

| 需求 | 內容 | 內部來源設定 |
|---|---|---|
| 基底映像檔 | `golang:1.26-bookworm` | 內部 registry |
| 系統套件 | `apt-get install` | `APK_MIRROR_ARG` |
| Go 依賴 | `go install .../migrate@latest`（第 50 行）、`go mod download`（第 56 行） | `GOPROXY_ARG`、`GOPRIVATE_ARG`、`GOSUMDB_ARG` |
| DuckDB 擴充 | `go run cmd/download/duckdb/duckdb.go`（第 58 行），執行 DuckDB 的 `INSTALL`，會從 DuckDB 官方的擴充套件庫下載 | 沒有預留設定 |
| Rust 工具鏈 | `curl https://sh.rustup.rs`（第 84 行），給 anydoc 用 | `WITH_ANYDOC=0` 可以跳過 |

**階段 3：執行階段映像檔（第 99 行之後）**

| 需求 | 內容 | 內部來源設定 |
|---|---|---|
| 基底映像檔 | `debian:12.12-slim` | 內部 registry |
| 系統套件 | `apt-get install` postgresql-client、python3、nodejs、npm… | `APK_MIRROR_ARG` |
| Python 工具 | `pip install --upgrade pip setuptools wheel` | 要設 pip 的 index-url |
| uv | `curl https://astral.sh/uv/install.sh`（第 132 行） | 沒有預留設定 |

**注意：`WITH_ANYDOC=0` 只能跳過階段 2 的那一次 rustup。**階段 1 的 browserskill 不管怎樣都會下載 Rust、clone GitHub、裝 npm 和 crates.io 套件。所以 app 映像檔就算有內部鏡像，也還需要 GitHub、rustup、crates.io、DuckDB 擴充庫、astral.sh 這幾個來源。要嘛公司鏡像也代理這些，要嘛改 Dockerfile。

### 2.3 `weknora-docreader`（`docker/Dockerfile.docreader`）

基底映像檔 `python:3.10.18-bookworm`、`apt-get`、`pip` / `uv` 套件、`protoc` 和 `grpc_health_probe`（都從 GitHub releases 下載）、Playwright 瀏覽器。只處理純文字的話可以不用它（見第 5 節）。

### 2.4 不用 build 的映像檔

`paradedb/paradedb:v0.25.11-pg17` 和 `redis:7.0-alpine` 不是 repo 自己 build 的，只能用現成的映像檔。

---

## 3. 怎麼把軟體帶進內網

### 3.1 走 IT／資安的引進流程（優先）

如果公司規定不能帶外部檔案進內網，就不要去繞過它。向 IT 申請引進軟體時，可以附上：

- **映像檔清單**：`docker compose config --images`。
- **來源與授權**：GitHub `Tencent/WeKnora`，Apache-2.0。repo 裡的 `LICENSE` 和 `THIRD_PARTY_NOTICES.md` 可以當作授權說明。
- **對外連線需求**：執行時不需要外連，可以用白名單模式強制（見第 4 節）。
- **build 來源**：可以全部指向公司內部鏡像（見 3.3）。

### 3.2 公司允許帶入檔案時：save / load

在有網路的機器上準備：

```bash
cd ~/Projects/AI-Engineer/WeKnora

# 先確認公司機器的 CPU 架構：Linux 伺服器通常是 linux/amd64，Apple Silicon Mac 是 linux/arm64
export DOCKER_DEFAULT_PLATFORM=linux/amd64

docker compose pull                 # 或 docker compose build 自己 build
docker compose config --images      # 確認要打包哪些映像檔
docker save $(docker compose config --images) | gzip > weknora-images.tar.gz
```

要帶進去的東西：`weknora-images.tar.gz`，加上 WeKnora repo（至少要有 `docker-compose.yml`、`.env`、`config/`、`migrations/`）。

在內網機器上：

```bash
docker load < weknora-images.tar.gz
docker compose up -d --pull never
```

**架構一定要對**：在 Apple Silicon Mac 上 pull 的映像檔預設是 arm64，帶到 amd64 的伺服器上會跑不起來，或是跑得非常慢。

### 3.3 公司有內部鏡像時：在內網直接 build

如果公司有 Nexus、Artifactory、Harbor 這類工具，能代理 Docker Hub、apt、npm、PyPI、Go modules，就可以在內網直接 build。`.env.example` 第 30-48 行有預留的來源設定：

```bash
APK_MIRROR_ARG=<公司的 Debian apt 鏡像>        # app 映像檔用
APT_MIRROR=<公司的 apt 鏡像>                    # docreader 映像檔用
PLAYWRIGHT_DOWNLOAD_HOST=<內部制品庫>           # docreader 的 Playwright 瀏覽器
NPM_REGISTRY=<內部 npm registry>               # 前端映像檔用（build arg）
GOPROXY_ARG=<內部 Go module proxy>             # app 映像檔用（build arg）
WITH_ANYDOC=0    # 跳過 Go builder 階段的 rustup，代價是 anydoc 的 Office 解析引擎不能用
```

另外還要設：Python 的 index-url，以及從內部 registry 拉的基底映像檔。

**沒有預留設定的來源**（app 映像檔才有）：GitHub（BrowserSkill 原始碼）、sh.rustup.rs 和 crates.io（browserskill 階段一定會用）、DuckDB 擴充庫、astral.sh（uv）。這些要請 IT 確認鏡像能不能代理，不行的話就要改 `docker/Dockerfile.app`。詳見第 2.2 節。

---

## 4. 執行時不連外網

### 4.1 必須放在內網的東西

| 元件 | 處理方式 |
|---|---|
| Postgres、Redis、docreader | 本來就在 docker compose 裡 |
| **LLM、embedding 模型** | 改用內網的 Ollama、vLLM，或公司提供的 OpenAI 相容 API。模型檔也要事先準備好。**這是最主要的一項，沒有模型的話 WeKnora 什麼都做不了。** |
| 檔案儲存 | 用預設的 `local`，不要接 COS、S3 |

### 4.2 不開就不會連網的功能

網路搜尋、IM 頻道（Slack、飛書…）、外部資料來源同步（Notion、Confluence…）、ClawHub 技能安裝、Langfuse。這些不需要從程式碼裡拿掉，不設定就不會用到。

### 4.3 白名單出站模式（v0.8.2 新增）

`.env.example` 第 785-797 行附近：

```bash
SSRF_DNS_WHITELIST_ONLY=true
SSRF_WHITELIST=ollama.internal,10.0.0.0/8   # 只列內網的模型、向量庫、物件儲存位址
```

開啟後，不在白名單裡的主機在 DNS 查詢之前就會被拒絕，確保系統不會往外連。這段設定也適合拿給資安審核當說明。

---

## 5. 只處理純文字時拿掉 docreader

### 5.1 為什麼可以

純文字格式和手動輸入的內容，由 Go 內建的 simple 引擎解析，不經過 docreader（`internal/infrastructure/docparser/engine_registry.go:69-79`）：

```go
if engine == "" && !isURL && IsSimpleFormat(fileType) {
    return &SimpleFormatReader{}, nil   // Go 內建，不需要 docreader
}
return remoteReader(deps)               // 其他格式才交給 docreader
```

simple 引擎支援的格式（`docparser/engines.go:113-119`）：

- **文字**：`md`、`markdown`、`txt`、`csv`、`json`
- 圖片和音訊也在清單裡，但要靠 VLM、ASR 模型才能抽出內容。

**還是需要 docreader 的情況**：PDF、Word、Excel、HTML、EPUB，以及**用網址匯入**。PPT 預設走 markitdown 引擎，也不能用。

`DOCREADER_ADDR` 留空的話，app 會以未連線狀態啟動（`internal/container/container.go:1694`）。這時只有上面那些格式會失敗，錯誤訊息是：`Document parsing service is not configured. Please use text/paragraph import or set DOCREADER_ADDR.`

### 5.2 怎麼設定（尚未實測）

`docker-compose.yml:395-396` 寫死了 app 要等 docreader healthy 才會啟動。建議不要改原檔，在 WeKnora 目錄新增 `docker-compose.override.yml`，compose 會自動合併：

```yaml
services:
  docreader:
    profiles: ["docreader"]        # 預設不啟動，需要時用 --profile docreader 打開
  app:
    environment:
      DOCREADER_ADDR: ""           # 以未連線狀態啟動
    depends_on: !override          # 取代原本的 depends_on，不再等 docreader
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
```

```bash
docker compose version             # !override 需要 Compose 2.24.4 以上
docker compose config --services   # 確認清單裡沒有 docreader
docker compose up -d
```

### 5.3 對離線部署的幫助

docreader 是 build 時最需要連網的部分（Python 依賴、Playwright 瀏覽器、protoc、grpc_health_probe）。拿掉之後，要準備的映像檔只剩：

- `wechatopenai/weknora-app`（自己 build 時加 `WITH_ANYDOC=0` 可以少一次 rustup，但 browserskill 階段還是要連網，見第 2.2 節）
- `wechatopenai/weknora-ui`
- `paradedb/paradedb:v0.25.11-pg17`
- `redis:7.0-alpine`

---

## 6. 其他選擇

- **Lite 版**：官方安裝文件把它列為適合「個人 / 離線 / 低資源環境」。在有網路的機器上用 `scripts/package-lite.sh` 打包成單一執行檔，不需要 Docker 和 Postgres。前提是打包的 OS 和架構要跟公司機器一致，而且同樣要經過公司的軟體引進流程。
- **llm-wiki**：如果在意的只是 WeKnora 建 wiki 的方式，`llm-wiki/` 這個 Python 版依賴比較少，也許比整套 WeKnora 更容易通過審核。前提是 `requirements.txt` 裡的套件公司允許使用，並且有能用的模型 API。
- **公司現有工具**：先問問公司是不是已經有核准的 RAG、知識庫平台或 LLM API。

---

## 7. 待確認

- [ ] 公司機器的 OS 和 CPU 架構
- [ ] 公司有沒有內部 registry 或套件鏡像
- [ ] 內網有沒有可以用的 LLM 和 embedding API
- [ ] 第 5.2 節的 override 設定實際跑一次，上傳 md 測試
