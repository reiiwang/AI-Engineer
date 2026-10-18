# 在公司內網 build weknora-ui

> 日期：2026-10-19 · 適用：WeKnora v0.8.2 `frontend/`
> **狀態：步驟是看程式碼推出來的，還沒有在公司內網實際 build 過。**
> 搭配使用：[`harbor-wiki-only/`](harbor-wiki-only/README.md)（執行）、[`self-build-issues.md`](self-build-issues.md)（三個映像檔的 build 問題總覽）

---

## 0. 前提

| 需要的東西 | 用途 |
|---|---|
| WeKnora 原始碼已經在公司內部（例如內部 GitLab） | build 的材料 |
| Harbor 有 Docker Hub 代理專案 | 拉 `node`、`nginx` 基底映像檔 |
| 內部 npm registry（Nexus、Artifactory 等） | 下載前端套件 |
| build 機器有 Docker，記憶體 8 GB 以上 | Vite build 預設會給 Node 4 GB |

以下用這些位址當例子，請換成公司實際的位址：

- Harbor Docker Hub 代理：`harbor.mycompany.com/dockerhub`
- 內部 npm registry：`https://nexus.mycompany.com/repository/npm/`

### 0.1 npm registry 是什麼

npm registry 是**存放 JavaScript 套件的伺服器**，可以想成套件的 App Store。

前端的 `package.json` 會列出需要哪些套件，例如 `vue`、`vite`、`mermaid`。執行 `npm install` 或 `npm ci` 時，npm 會去 registry：

1. 查這個套件有哪些版本；
2. 下載對應版本的壓縮檔（`.tgz`）；
3. 解壓縮到 `node_modules/`。

WeKnora 前端有幾百個這樣的套件，全部都要從 registry 下載。

| 種類 | 例子 | 說明 |
|---|---|---|
| 官方公開 registry | `https://registry.npmjs.org` | npm 預設會連這裡，要能連外網 |
| 公開鏡像 | `mirrors.tencent.com/npm`、`registry.npmmirror.com` | 別人複製的官方內容，主要給中國用來加速。WeKnora 的 lock 檔裡大部分網址就是這些 |
| **公司內部 registry** | Nexus、Artifactory、Verdaccio | 架在公司內網，替你去外面抓套件並存起來（代理快取），內網機器只連它就好 |

### 0.2 跟 Harbor 的關係

概念一樣，只是管的東西不同：

| | 存什麼 | 公司有沒有 |
|---|---|---|
| **Harbor** | Docker 映像檔 | 有 |
| **npm registry** | JavaScript 套件 | **待確認** |
| PyPI 鏡像 | Python 套件 | 待確認（build ui 不需要） |

**Harbor 只管 Docker 映像檔，不能拿來下載 npm 套件。**所以要在公司 build `weknora-ui`，除了 Harbor，還一定要有內部 npm registry。

### 0.3 到公司要確認的事

**1. 公司機器上是不是已經有人設定過 npm registry**

```bash
npm config get registry     # 如果不是 https://registry.npmjs.org/，可能就是公司內部的
cat ~/.npmrc                # 看有沒有 registry= 這一行
cat /etc/npmrc 2>/dev/null  # 系統層級的設定
```

公司機器上沒有 npm 的話，這兩個指令會失敗。這時直接問 IT 就好。

**2. 問 IT**

- 公司有沒有內部的 npm registry，或是 Nexus、Artifactory 這類套件代理？網址是什麼？需不需要帳號？
- 它是不是**代理**整個 npmjs.org，還是只有事先同步的套件？只同步部分套件的話，幾百個套件很可能會缺。
- Harbor 的 Docker Hub 代理專案名稱是什麼？（第 2.4 節的 `FROM` 會用到）
- 公司網路會不會攔截並重簽 HTTPS？如果會，根憑證要去哪裡拿？（第 2.4 節 (3)）

**3. 測試 registry 能不能用**

拿到網址之後，先用一個小套件測試：

```bash
npm view vue version --registry=https://nexus.mycompany.com/repository/npm/
```

印出版本號就代表能用。

| 結果 | 下一步 |
|---|---|
| **有內部 npm registry，而且能用** | 照這份文件第 1-5 節 build |
| **沒有內部 npm registry** | 沒辦法在內網 build 前端。改照 [`harbor-wiki-only/`](harbor-wiki-only/README.md) 的做法，從 Harbor 直接拉官方已經 build 好的 `weknora-ui` 映像檔，完全不需要 npm |

---

## 1. 先決定 xlsx 要怎麼處理

### 1.1 xlsx 是做什麼的

`xlsx`（SheetJS）不在 npm registry 上，而是直接從 SheetJS 的 CDN 下載：

```
frontend/package.json:40         "xlsx": "https://cdn.sheetjs.com/xlsx-0.20.2/xlsx-0.20.2.tgz"
frontend/package-lock.json:5568  "resolved": "https://cdn.sheetjs.com/xlsx-0.20.2/xlsx-0.20.2.tgz"
```

所以內部 npm registry 代理不到它，在內網一定會下載失敗。

前端只有兩個地方用到它：

| 位置 | 用途 | 用到的函式 |
|---|---|---|
| `src/components/document-preview.vue:282` | 預覽 csv、xlsx 檔時把表格畫出來（用時才載入） | `read`、`utils.sheet_to_html` |
| `src/views/knowledge/components/FAQEntryManager.vue:785` | FAQ 類型知識庫的 Excel 匯入、匯出和範本下載 | `read`、`writeFile`、`utils.sheet_to_json`、`utils.json_to_sheet`、`utils.book_new`、`utils.book_append_sheet` |

**只用 wiki、手動輸入 txt 的話，這兩個功能都用不到，所以 xlsx 不是必要的。**

### 1.2 三個選項

| 選項 | 做法 | 代價 | 建議 |
|---|---|---|---|
| **A. 拿掉** | 用 Vite alias 換成空的替代模組 | csv、xlsx 預覽和 FAQ 的 Excel 匯入匯出不能用 | **推薦** |
| B. 保留同一版 | 請 IT 把 `xlsx-0.20.2.tgz` 放進內部制品庫（例如 Nexus raw），再把 `package.json` 和 `package-lock.json` 裡的網址換掉。檔案內容一樣，integrity hash 不用改 | 要 IT 幫忙處理檔案 | 需要那些功能時再考慮 |
| C. 換成 npm 上的版本 | npm registry 上最後一版是 `xlsx@0.18.5` | 這版有已知的安全漏洞（原型污染、ReDoS） | **不要用** |

下面的步驟用選項 A。

---

## 2. 修改原始碼

以下都在 WeKnora repo 的 `frontend/` 目錄裡做。

### 2.1 新增 xlsx 替代模組

新增 `frontend/src/stubs/xlsx.ts`：

```ts
// 此部署不包含 SheetJS（xlsx），呼叫時直接報錯。
// 影響範圍：csv/xlsx 預覽、FAQ 知識庫的 Excel 匯入匯出。
const unsupported = (): never => {
  throw new Error('此部署未啟用 Excel 功能（xlsx 已移除）')
}

export const read = unsupported
export const writeFile = unsupported
export const utils = {
  sheet_to_html: unsupported,
  sheet_to_json: unsupported,
  json_to_sheet: unsupported,
  book_new: unsupported,
  book_append_sheet: unsupported,
}
```

### 2.2 在 `vite.config.ts` 加上 alias

找到 `resolve.alias`（大約第 124-128 行），加一行 `xlsx`：

```ts
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@vue-office/pptx': resolveVueOfficePptxEntry(),
      xlsx: fileURLToPath(new URL('./src/stubs/xlsx.ts', import.meta.url)),
    },
  },
```

這樣兩個 `.vue` 檔都不用改。`npm run build` 只會執行 `vite build`，不跑 `vue-tsc` 型別檢查，所以型別不完整也不會擋住 build。

### 2.3 從依賴裡移除 xlsx

在公司內網執行，讓 `package.json` 和 `package-lock.json` 同步拿掉 xlsx：

```bash
cd frontend
npm uninstall xlsx --registry=https://nexus.mycompany.com/repository/npm/
git diff --stat package.json package-lock.json   # 確認只有 xlsx 相關的變更
```

如果這一步因為其他套件下載失敗而卡住，可以改成手動編輯：

- `package.json`：刪掉 `"xlsx": "https://cdn.sheetjs.com/..."` 那一行。
- `package-lock.json`：
  - 刪掉 `packages[""].dependencies` 裡的 `xlsx`；
  - 刪掉整個 `"node_modules/xlsx": { ... }` 區塊（大約第 5566 行）。

### 2.4 修改 `frontend/Dockerfile`

**(1) 兩個 `FROM` 改成 Harbor 路徑**。Docker Hub 官方映像檔要加 `library/`，digest 可以保留：

```dockerfile
FROM --platform=$BUILDPLATFORM harbor.mycompany.com/dockerhub/library/node:24-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS builder
```

```dockerfile
FROM harbor.mycompany.com/dockerhub/library/nginx:1.30.3-alpine@sha256:0d3b80406a13a767339fbe2f41406d6c7da727ab89cf8fae399e81f780f814d1
```

**(2) `npm ci` 加上 `--replace-registry-host=always`**（大約第 39-43 行）：

```dockerfile
RUN if [ -n "$NPM_REGISTRY" ]; then \
      npm ci --registry="$NPM_REGISTRY" --replace-registry-host=always; \
    else \
      npm ci; \
    fi
```

這一步是必要的：`package-lock.json` 裡有 341 個套件的網址寫死成 `mirrors.tencent.com`，1 個是 `registry.npmmirror.com`。npm 預設只會把 `registry.npmjs.org` 換成你設的 registry，其他網址照原樣下載，加了這個參數才會全部換掉。

**(3) 公司會攔截並重簽 HTTPS 時才需要**：在 builder 階段的 `npm ci` 之前加入公司根憑證。

```dockerfile
COPY company-root-ca.crt /usr/local/share/ca-certificates/company-root-ca.crt
RUN update-ca-certificates
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/company-root-ca.crt
```

`node:24-bookworm-slim` 可能沒有 `update-ca-certificates`。如果沒有，只設 `NODE_EXTRA_CA_CERTS` 也夠 npm 使用。

---

## 3. build

在 WeKnora repo 根目錄：

```bash
docker build \
  --build-arg NPM_REGISTRY=https://nexus.mycompany.com/repository/npm/ \
  -t weknora-ui:v0.8.2-wiki \
  frontend/
```

- 記憶體不夠時，加上 `--build-arg NODE_MAX_OLD_SPACE_SIZE=2048`。
- 想在系統資訊頁顯示 commit，加上 `--build-arg VITE_FRONTEND_COMMIT=$(git rev-parse --short HEAD)`。

build 完成後，**映像檔就存在這台機器的 Docker 裡**：

```bash
docker images | grep weknora-ui
```

---

## 4. 使用 build 好的映像檔

### 4.1 在同一台機器執行：不需要 push

修改 `harbor-wiki-only/docker-compose.yml` 的 frontend：

```yaml
  frontend:
    image: weknora-ui:v0.8.2-wiki
```

```bash
cd harbor-wiki-only
docker compose up -d --pull never   # --pull never：只用本機的映像檔，不去 Harbor 拉
```

其他三個服務（app、postgres、redis）還是照原本的設定從 Harbor 拉。

### 4.2 什麼時候才需要 push 到 Harbor

- build 和執行不在同一台機器；
- 要給同事用，讓別人不用自己 build；
- 想留備份：本機映像檔會被 `docker compose down --rmi all` 或 `docker image prune` 刪掉。

```bash
docker tag weknora-ui:v0.8.2-wiki harbor.mycompany.com/<你的專案>/weknora-ui:v0.8.2-wiki
docker login harbor.mycompany.com
docker push harbor.mycompany.com/<你的專案>/weknora-ui:v0.8.2-wiki
```

push 要有那個 Harbor 專案的寫入權限。之後 compose 的 `image:` 改成 Harbor 的完整路徑。

---

## 5. 驗證

1. 打開 `http://<機器 IP>`，可以正常登入和進入知識庫。
2. 建一個只勾 wiki 的知識庫，手動輸入一段文字，確認 wiki 頁籤、資料夾樹和圖譜都正常顯示。
3. 確認 xlsx 的替代模組只影響預期的功能：預覽 csv 或使用 FAQ Excel 匯入時，應該出現「此部署未啟用 Excel 功能」的錯誤，其他頁面不受影響。

---

## 6. 可能遇到的問題

| 症狀 | 原因 | 處理 |
|---|---|---|
| `npm ci` 卡在 `cdn.sheetjs.com` | xlsx 沒有完全拿掉 | 確認 `package.json` 和 `package-lock.json` 都沒有 `sheetjs` 了：`grep -n sheetjs frontend/package*.json` |
| `npm ci` 連到 `mirrors.tencent.com` 失敗 | 沒加 `--replace-registry-host=always` | 見 2.4 (2) |
| `npm ci` 報 `package.json and package-lock.json are not in sync` | 2.3 只改了其中一個檔案 | 兩個檔案都要拿掉 xlsx |
| esbuild 安裝時嘗試連 `registry.npmjs.org` | 內部 registry 沒同步到對應平台的 `@esbuild/linux-x64` | 請 IT 確認有同步 `@esbuild/*` 套件 |
| `vite build` 報 `Failed to resolve import "xlsx"` | 2.2 的 alias 沒加，或路徑寫錯 | 檢查 `vite.config.ts` |
| build 時記憶體不足（`JavaScript heap out of memory`） | 機器記憶體不夠 | 調低 `NODE_MAX_OLD_SPACE_SIZE`，或換一台記憶體更大的機器 build |
| 拉基底映像檔時 `manifest unknown` | Harbor 路徑錯誤，或少了 `library/` | 先手動 `docker pull` 那個 `FROM` 的完整路徑測試 |
| 憑證錯誤（`UNABLE_TO_GET_ISSUER_CERT_LOCALLY`、`SELF_SIGNED_CERT_IN_CHAIN`） | 公司會攔截並重簽 HTTPS | 見 2.4 (3) |

---

## 7. 改了哪些檔案（之後升級 WeKnora 要重新套用）

| 檔案 | 改動 |
|---|---|
| `frontend/src/stubs/xlsx.ts` | 新增 |
| `frontend/vite.config.ts` | `resolve.alias` 加一行 `xlsx` |
| `frontend/package.json`、`frontend/package-lock.json` | 移除 xlsx |
| `frontend/Dockerfile` | 兩個 `FROM` 改成 Harbor；`npm ci` 加 `--replace-registry-host=always`；必要時加公司憑證 |

建議在內部 GitLab 開一個分支保存這些改動，升級時再 rebase 到新版本上。
