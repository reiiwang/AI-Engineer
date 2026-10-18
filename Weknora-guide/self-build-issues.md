# 在公司內網自己 build WeKnora 映像檔會遇到的問題

> 日期：2026-10-19 · 依據：WeKnora v0.8.2 原始碼（`frontend/Dockerfile`、`docker/Dockerfile.app`、`docker/Dockerfile.docreader` 和相關腳本）
> 前提：公司機器不能連外網，有 Harbor，其他套件來源要看 IT 能提供什麼。
> **狀態：這些問題是讀 Dockerfile 推出來的，還沒有在公司實際 build 過。**

如果不需要修改 WeKnora 的程式碼，**建議直接從 Harbor 拉官方映像檔**（見 [`harbor-wiki-only/`](harbor-wiki-only/README.md)），這份文件列的問題全部都不會遇到。

---

## 0. 開始 build 之前就會卡住的問題

| 問題 | 說明 | 怎麼解 |
|---|---|---|
| **原始碼要怎麼拿到公司** | build 需要整個 WeKnora repo。帶不進壓縮包的話，原始碼也一樣帶不進來 | 問 IT 有沒有內部 GitLab 或 GitHub 鏡像可以同步 `Tencent/WeKnora`。沒有的話，這條路從一開始就走不通 |
| **`FROM` 寫死 Docker Hub** | 每個 Dockerfile 的 `FROM` 都是 Docker Hub 的映像檔，例如 `node:24-bookworm-slim@sha256:...`、`golang:1.26-bookworm`、`debian:12.12-slim`、`python:3.10.18-bookworm`、`nginx:1.30.3-alpine` | 把 `FROM` 改成 Harbor 路徑，例如 `harbor.mycompany.com/dockerhub/library/node:24-bookworm-slim@sha256:...`。Harbor 的 proxy cache 專案帶有專案名稱的路徑，通常沒辦法直接設成 Docker daemon 的 `registry-mirrors`，所以要改 Dockerfile |
| **公司的 TLS 憑證** | 如果公司網路會攔截並重簽 HTTPS（常見於有資安閘道的環境），容器裡的 `curl`、`npm`、`go`、`pip`、`cargo` 都會出現憑證錯誤 | 在每個 build 階段一開始，把公司根憑證複製進 `/usr/local/share/ca-certificates/` 並執行 `update-ca-certificates`。npm、pip、cargo 可能還要各自指定憑證路徑 |
| **build 資源** | 前端 build 預設給 Node 4 GB 記憶體（`NODE_MAX_OLD_SPACE_SIZE=4096`），app 要編譯 Rust（browserskill、anydoc）和 Go，很吃 CPU 和硬碟 | build 機器建議至少 8 GB 記憶體，並留 20 GB 以上硬碟空間 |

---

## 1. `weknora-ui`（`frontend/Dockerfile`）

三個映像檔裡最容易 build 的一個，不過還是有兩個陷阱。完整的 build 步驟見 [`build-weknora-ui.md`](build-weknora-ui.md)。

| 問題 | 原因 | 位置 | 怎麼解 |
|---|---|---|---|
| 設了 `NPM_REGISTRY` 還是連到外網 | `package-lock.json` 裡 341 個套件的下載網址寫死成 `https://mirrors.tencent.com`。npm 預設只會把 `registry.npmjs.org` 換成你設的 registry，其他網址照原樣下載 | `frontend/package-lock.json` | 改用 `npm ci --replace-registry-host=always --registry=<內部 registry>`（要修改 Dockerfile 第 39-42 行），或請 IT 讓內部鏡像也代理 `mirrors.tencent.com` |
| `xlsx` 套件下載失敗 | `xlsx` 不在 npm registry 上，是直接從 SheetJS 的 CDN 下載 tarball：`https://cdn.sheetjs.com/xlsx-0.20.2/xlsx-0.20.2.tgz` | `frontend/package.json:40`、`package-lock.json:5568` | npm registry 鏡像處理不了這種直接網址。要請 IT 用 Nexus 的 raw proxy 之類的方式提供，或者事先把這個檔案放到內部制品庫，再改 `package.json` 的網址 |

---

## 2. `weknora-app`（`docker/Dockerfile.app`）

需要連網最多的一個。分三個 build 階段，每個階段都有問題。

### 2.1 browserskill 階段（第 1-24 行，一定會執行）

這個階段沒有開關可以關掉。

| 問題 | 原因 | 怎麼解 |
|---|---|---|
| 設了 apt 鏡像，第一次 `apt-get update` 還是連外網 | 設了 `APK_MIRROR_ARG` 時，Dockerfile 會**先用原本的 `deb.debian.org`** 裝 `ca-certificates`，然後才換成鏡像（第 9-13 行，是為了處理鏡像會把 HTTP 轉向 HTTPS 的問題） | 修改 Dockerfile，一開始就換成內部鏡像。內部鏡像如果是 HTTP 就沒有這個問題 |
| 下載 Rust 失敗 | `curl https://sh.rustup.rs`（第 20 行） | 請 IT 提供 rustup 鏡像（設 `RUSTUP_DIST_SERVER`、`RUSTUP_UPDATE_ROOT`），或改用已經裝好 Rust 的基底映像檔 |
| clone GitHub 失敗 | `git clone https://github.com/Tencent/BrowserSkill.git`，固定在 commit `da6bf4e`（`scripts/build_browserskill.sh:35`、`scripts/browserskill-release.json`） | 需要內部 Git 鏡像，並修改腳本裡的網址 |
| pnpm 失敗 | `npx --yes pnpm@10.17.0`，pnpm 本身也要從 npm 下載 | 設 npm registry 環境變數 |
| `cargo build` 失敗 | 從 crates.io 下載 Rust 套件 | 請 IT 提供 crates.io 鏡像，並在 `~/.cargo/config.toml` 設定 `source.crates-io` 的替代來源 |
| 如果這些都解決不了 | — | 修改 Dockerfile 拿掉整個 browserskill 階段，同時拿掉執行階段的 `COPY --from=browserskill`（第 106-108 行）。代價是 agent 不能用「本機瀏覽器」功能，只用 wiki 的話沒有影響 |

### 2.2 Go builder 階段（第 27-96 行）

| 問題 | 原因 | 怎麼解 |
|---|---|---|
| `go mod download` 失敗 | 預設連 `proxy.golang.org` | build arg `GOPROXY_ARG=<內部 Go proxy>`。`GOSUMDB_ARG` 預設已經是 `off` |
| `go install migrate@latest` 每次結果可能不同 | 第 50 行用 `@latest`，內部 proxy 快取的版本和外面不一定一樣 | 能 build 就好，要穩定的話改成固定版本 |
| DuckDB 擴充下載失敗 | `go run cmd/download/duckdb/duckdb.go`（第 58 行）會執行 DuckDB 的 `INSTALL spatial`、`INSTALL excel`，從 DuckDB 官方擴充庫下載。失敗時會直接 panic，build 中止 | **沒有預留設定。**要請 IT 代理 DuckDB 擴充庫並修改程式設定 `custom_extension_repository`，或者修改 Dockerfile 跳過這步。跳過的代價是資料分析工具的 spatial、excel 功能不能用 |
| anydoc 的 Rust 下載失敗 | 第 84 行又裝一次 rustup，`scripts/build-anydoc-lib.sh` 再從 `rsproxy.cn` 或 `static.crates.io` 下載 anydoc 套件 | build arg `WITH_ANYDOC=0` 可以整段跳過。代價是 Office 檔解析引擎不能用，只用 wiki 的話沒有影響 |

### 2.3 執行階段（第 99 行之後）

| 問題 | 原因 | 怎麼解 |
|---|---|---|
| 第一次 `apt-get update` 一定連外網 | 第 114-116 行**不管有沒有設鏡像**，都先用原本的來源裝 `ca-certificates`，第 119 行之後才換鏡像 | 一定要修改 Dockerfile，把換鏡像的步驟移到最前面 |
| `pip install --upgrade pip setuptools wheel` 失敗 | 連 PyPI | 在 Dockerfile 設 `PIP_INDEX_URL=<內部 PyPI 鏡像>` |
| 下載 uv 失敗 | `curl https://astral.sh/uv/install.sh`（第 132 行） | **沒有預留設定。**改成 `pip install uv`（走內部 PyPI），或拿掉。uv 是給 agent 技能（`uvx`）用的，只用 wiki 的話沒有影響 |

---

## 3. `weknora-docreader`（`docker/Dockerfile.docreader`）

只用 wiki、手動輸入文字的話**不需要這個映像檔**（見 [`offline-deployment.md`](offline-deployment.md) 第 5 節），可以直接跳過。

| 問題 | 原因 | 怎麼解 |
|---|---|---|
| apt | 有 `APT_MIRROR` build arg，會換掉 `deb.debian.org` 和 `security.debian.org` | 設成內部鏡像即可 |
| `protoc` 下載失敗 | 從 GitHub releases 下載 `protobuf v3.19.4`（第 60 行） | 沒有預留設定，要內部制品庫並修改 Dockerfile |
| Python 套件下載失敗 | `uv sync --locked`（第 69 行），`docreader/uv.lock` 裡 90 個套件都寫死來源是 `https://pypi.org/simple` | 要設 uv 的 index 來源。因為 lock 檔記錄了來源網址，換成其他來源時 `--locked` 很可能會報錯，可能要重新產生 lock 檔 |
| `grpc_health_probe` 下載失敗 | 從 GitHub releases 下載（第 135 行） | 沒有預留設定，要內部制品庫並修改 Dockerfile |
| Playwright 瀏覽器下載失敗 | `playwright install webkit` 從 Playwright CDN 下載（第 146-155 行） | build arg `PLAYWRIGHT_DOWNLOAD_HOST=<內部制品庫>` |
| `playwright install-deps` 失敗 | 用 apt 裝瀏覽器需要的系統套件（第 155 行） | apt 鏡像設好就能解決 |

---

## 4. 要向 IT 確認的來源清單

把這張表拿給 IT，逐項確認公司內部能不能提供。

| 來源 | 給誰用 | 只用 wiki 時需要嗎 |
|---|---|---|
| WeKnora 原始碼（內部 Git 鏡像） | 全部 | **需要** |
| Docker Hub（Harbor proxy cache） | 全部的 `FROM` | **需要** |
| Debian apt 鏡像 | app、docreader | **需要** |
| npm registry（含 `mirrors.tencent.com` 的套件） | ui、app 的 browserskill | **需要**（ui） |
| `cdn.sheetjs.com` 的 xlsx tarball | ui | **需要** |
| Go module proxy | app | **需要** |
| PyPI 鏡像 | app、docreader | **需要**（app 的 pip） |
| rustup、crates.io 鏡像 | app 的 browserskill、anydoc | 改 Dockerfile 拿掉 browserskill，並設 `WITH_ANYDOC=0`，就不需要 |
| GitHub（BrowserSkill、protoc、grpc_health_probe） | app、docreader | 拿掉 browserskill、不 build docreader，就不需要 |
| DuckDB 擴充庫 | app | 改 Dockerfile 跳過，就不需要 |
| astral.sh（uv） | app | 改 Dockerfile 拿掉或改成 pip 安裝，就不需要 |
| Playwright CDN | docreader | 不 build docreader，就不需要 |

## 5. 只用 wiki 時，最少要改的地方

1. 所有 `FROM` 改成 Harbor 路徑。
2. 如果公司會攔截 HTTPS，每個階段加入公司根憑證。
3. **ui**：npm 加上 `--replace-registry-host=always`，並處理 xlsx 的直接網址。
4. **app**：
   - 拿掉 browserskill 階段和對應的 `COPY`；
   - 設 `WITH_ANYDOC=0`、`GOPROXY_ARG`、`APK_MIRROR_ARG`；
   - 把執行階段的換鏡像步驟移到第一次 `apt-get update` 之前；
   - 跳過 DuckDB 擴充下載；
   - uv 改成用 pip 安裝或拿掉；
   - 設 `PIP_INDEX_URL`。
5. **docreader**：不 build。

改這麼多的話，維護成本很高：之後每次升級 WeKnora 都要重新套用一次。**除非一定要改程式碼，不然從 Harbor 拉官方映像檔會簡單很多。**
