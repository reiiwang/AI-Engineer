# llm-wiki 的 wiki 建立 pipeline

> 狀態：參考文件 · 日期：2026-10-20 · 作者：rywang
> 對象：`llm-wiki/wikibuilder/`（參考 WeKnora 的 wiki 建立方式用 Python 重寫）
> 相關文件：WeKnora 原版 pipeline 的說明見 [`../weknora-wiki-pipeline.md`](../weknora-wiki-pipeline.md)；兩邊實際跑出來的差異見 [`weknora-docker-comparison.md`](weknora-docker-comparison.md)

---

## 0. 怎麼讀這份文件

這份文件說明 llm-wiki **自己的程式碼**怎麼把 `raw/` 裡的 markdown 變成 `wiki/` 裡的頁面：

- 有哪些階段，每個階段的輸入、輸出和失敗時的行為；
- 每一次 LLM 呼叫在哪裡、用哪個 prompt、輸出什麼格式；
- 哪些內容是規則產生的，哪些是 LLM 寫的；
- 文件新增、修改、刪除時，怎麼增量更新。

prompt 全文在 `wikibuilder/prompts.py`，是從 WeKnora 的 `internal/agent/prompts_wiki.go` 原封不動搬過來的，保留 Go 的 `{{.Var}}` 樣板語法。這份文件只講每個 prompt 的用途和輸入輸出。

用語：

| 用語 | 意思 |
|---|---|
| **doc** | `raw/` 裡的一份來源文件，ID 是相對於 `raw/` 的路徑，例如 `cirrus-architecture.md` |
| **chunk** | doc 切出來的片段，是引用的最小單位，ID 是 `<doc_id>#c0003` |
| **slug** | 頁面 ID，同時帶有類型前綴：`entity/xxx`、`concept/xxx`、`summary/xxx`、`index` |
| **item** | 從 doc 抽出來的 entity 或 concept 候選（`ExtractedItem`） |
| **SlugUpdate** | 「要對某個 slug 做的一次修改」，map 階段產生、reduce 階段消化 |
| **state** | `.wiki_state/state.json`，整個 wiki 的正式資料。`wiki/` 是從它渲染出來的 |

---

## 1. 全貌

```
python build_wiki.py
  │
  ├─ 1. 讀 state           .wiki_state/state.json
  ├─ 2. 比對 raw/          sha256 → added / changed / removed / unchanged
  ├─ 3. 處理刪除的 doc      拿掉來源引用（沒來源的頁面直接刪）→ 排一個 retract op
  ├─ 4. 載入新增或修改的 doc  切 chunk → 排 ingest op
  │
  ├─ 5. 每 5 個 op 一批（docs_per_batch）
  │     ├─ 5a retract op → 對它影響過的每一頁產生 retract 更新
  │     ├─ 5b map（每份 doc 平行處理）
  │     │     Pass 0 抽候選 → dedup → [ 摘要 ∥ chunk 引用 ] → 和上一版比對
  │     ├─ 5c identity remap   同一批裡同名不同 slug 的合併
  │     ├─ 5d taxonomy         幫還沒分類的頁面分資料夾
  │     ├─ 5e reduce（每個 slug 平行處理）  LLM 重寫頁面
  │     └─ 5f 記錄 doc、存 state
  │
  ├─ 6. finalize（整次執行只跑一次）
  │     index 介紹 → 清死連結 → 自動加交叉連結
  │
  └─ 7. render              state → wiki/（wiki_format.py）
```

入口是 `build_wiki.py`，主要邏輯在 `wikibuilder/pipeline.py:207` 的 `build()`。

### 1.1 執行模式

| 指令 | 行為 |
|---|---|
| `python build_wiki.py` | 增量建立，只處理新增、修改、刪除的 doc |
| `--dry-run` | 只印出 added / changed / removed，不呼叫 LLM、不寫檔 |
| `--rebuild` | 刪掉 `.wiki_state/`，全部重建。會保留上次渲染過的檔案清單，讓重新渲染時能清掉舊檔（`pipeline.py:209-214`） |
| `--render-only` | 不呼叫 LLM，只從 state 重新渲染 `wiki/`。改了 `wiki_format.py` 時用 |

---

## 2. 資料結構（`wikibuilder/models.py`）

| 類別 | 用途 | 重要欄位 |
|---|---|---|
| `SourceDoc` | 一份載入的 doc | `id`、`title`、`content`（去掉 frontmatter）、`hash`、`chunks` |
| `Chunk` | doc 的片段 | `id`（`<doc_id>#c0003`）、`index`、`content` |
| `DocRecord` | state 記住的 doc 資訊 | `hash`、`title`、`summary_slug`、`summary_line`、`summary_body` |
| `ExtractedItem` | 抽出來的 entity / concept | `name`、`slug`、`aliases`、`description`、`details`、`source_chunks` |
| `SlugUpdate` | 對某個 slug 的一次修改 | `slug`、`type`、`doc_id`、`item`、`doc_summary`、`retract_doc_content` |
| `WikiPage` | 一個 wiki 頁面 | `slug`、`title`、`page_type`、`content`、`summary`、`aliases`、`source_refs`、`chunk_refs`、`category`、`version` |
| `Op` | 一個待處理的工作 | `kind`（`ingest` 或 `retract`）、`doc` 或刪除時的快照 |

`SlugUpdate.type` 有五種：

| type | 來源 | 意思 |
|---|---|---|
| `summary` | map | 這份 doc 的摘要頁 |
| `entity` / `concept` | map | 這份 doc 提到這個 entity / concept，要把新內容加進去 |
| `retract` | map 或刪除 | doc 被修改但還提到這頁，要先拿掉舊版的貢獻；或 doc 被刪掉 |
| `retractStale` | map | doc 被修改，**已經不再**提到這頁，要拿掉它的貢獻 |

---

## 3. 規劃：要處理哪些 doc（`pipeline.py:49`）

`make_plan()`：

1. 用 `config.yaml` 的 `include`（預設 `**/*.md`）掃 `raw/`，略過任何以 `.` 開頭的路徑（`chunker.py:137-143`）。
2. 和 `state.docs` 比對：
   - state 裡沒有 → **added**
   - 有，但檔案的 sha256 不同 → **changed**
   - 有，而且 hash 一樣 → **unchanged**（完全不處理）
   - state 裡有、`raw/` 裡沒有 → **removed**

**提早結束**（`pipeline.py:236-240`）：沒有任何變動，而且 index 介紹已經存在，就只重新渲染、存檔後結束。如果有 doc 但沒有 index 介紹，代表上次在 finalize 之前就中斷了，所以會繼續往下跑完。

---

## 4. 刪除的 doc（`pipeline.py:64`）

`remove_document()` 不呼叫 LLM，只做規則處理：

1. 從 `state.docs` 拿掉這份 doc 的紀錄。
2. 找出所有 `source_refs` 有它的頁面，從 `source_refs` 和 `chunk_refs` 拿掉它。
3. **拿掉之後沒有任何來源的頁面，直接刪除**（WeKnora 會留下一個「空頁面」，這裡不留）。
4. 排一個 `retract` op，帶著 doc 的標題、一行摘要和受影響的頁面清單。之後由 reduce 階段請 LLM 把這份 doc 獨有的內容從還留著的頁面中刪掉。

處理完立刻存 state。

---

## 5. 載入與切 chunk（`wikibuilder/chunker.py`）

### 5.1 載入（`load_document()`，第 124 行）

- 拆出 frontmatter（用 YAML 解析，解析失敗就當作沒有）。
- **標題**：frontmatter 的 `title` → 第一個 `# ` 標題 → 檔名。
- **hash**：整份檔案（含 frontmatter）的 sha256。
- **content**：去掉 frontmatter 後的內文。

### 5.2 切 chunk（`chunk_markdown()`，第 85 行）

WeKnora 用 docreader 服務切 chunk，這裡自己用規則切：

1. **先切成區塊**（`_blocks()`）：
   - 空行分隔段落；
   - 每個標題自己是一個區塊；
   - fenced code block（` ``` ` 或 `~~~`）整塊保留，不會從中間切開。
2. **再把區塊裝進 chunk**，上限是 `chunk_size`（預設 1000 字元）：
   - 加入下一個區塊會超過上限 → 開新 chunk；
   - 遇到標題，而且目前的 chunk 已經有 `chunk_size / 3` 以上的內容 → 開新 chunk，讓同一節盡量待在一起；
   - 單一區塊就超過上限 → 在上限前最後一個換行或空白切開（`_hard_split()`）。前面還沒放出去的標題會跟著這個大區塊。
3. chunk ID 是 `<doc_id>#c0000`、`#c0001`……同一個 doc 版本內穩定。

---

## 6. 分批（`pipeline.py:252-266`）

所有 op 依序排好：**先放刪除產生的 retract op，再放新增和修改的 ingest op**。然後每 `docs_per_batch`（預設 5）個切成一批。retract op 也算在一批的數量裡。

每批跑完 `process_batch()` 就存一次 state，所以中途中斷時，已經完成的批次不會白做。

---

## 7. 一批的處理（`pipeline.py:116` `process_batch()`）

### 7a. retract op 轉成更新

每個 retract op，對它記錄的每一頁產生一個 `retract` 類型的 SlugUpdate，`retract_doc_content` 是刪除時存下的摘要。

### 7b. map：把一份 doc 變成一串 SlugUpdate（`extract.py:182` `map_document()`）

ingest op 用 `ThreadPoolExecutor(map_parallel)` 平行處理，預設 4 個。

**(1) 前置檢查**

- 內容截到 `max_content_chars`（預設 32768 字元）。
- 去掉圖片標記後少於 10 個字元 → 跳過這份 doc（`extract.py:184-186`）。
- 記下這份 doc 目前餵養的頁面（`old_slugs`），後面比對用。

**(2) Pass 0：抽候選 entity / concept**（`_extract_candidates()`，第 66 行）

| | |
|---|---|
| prompt | `WIKI_CANDIDATE_SLUG_PROMPT` |
| 輸入 | 內文、語言、`PreviousSlugs`（這份 doc 上次產生過的 entity/concept slug，讓 LLM 盡量沿用）、粒度和粒度說明 |
| 輸出 | JSON：`entities`、`concepts`，每個有 `name`、`slug`、`aliases`、`description` |
| 失敗時 | 改用 `WIKI_KNOWLEDGE_EXTRACT_PROMPT` 一次抽完（輸出多了 `details`），並標記 `fallback`，之後**不做 chunk 引用** |

粒度（`config.yaml` 的 `granularity`）有三種：`focused`、`standard`（預設）、`exhaustive`，各自有一段指引插進 prompt（`prompts.py:476-524`）。

抽出來的 slug 會被正規化：去掉類型前綴、`slugify()`（小寫，只保留 a-z、0-9、`-`、`/` 和中日韓字元，`links.py:13`），再加上 `entity/` 或 `concept/`。

**(3) dedup：合併成已經存在的頁面**（`dedup.py:102` `deduplicate()`）

比對的對象是這一批開始時就存在的所有 entity / concept 頁面。

1. item 的 slug 已經是現有頁面 → 跳過，這是重新 ingest，不是合併。
2. **完全同名**（去空白、小寫後相同）→ 直接合併，同類型優先，其次跨類型（`_exact_target()`）。
3. 其他的 item，用相似度挑候選頁面（取代 WeKnora 用的 pg_trgm）：
   - 分數：slug token 的 Jaccard，以及名稱、別名的字元 bigram Jaccard，取最大值；
   - 每個 item 取前 5 名，分數至少 0.08。
4. 有候選的 item 一起送一次 LLM：

| | |
|---|---|
| prompt | `WIKI_DEDUPLICATION_PROMPT` |
| 輸入 | 每個 item 和它自己的候選頁面（XML） |
| 輸出 | JSON：`merges: {新 slug: 現有 slug}` |
| 驗證 | 目標必須在**這個 item 自己的**候選清單裡，而且類型相同，否則拒絕 |
| 失敗時 | 當作沒有任何合併 |

合併的做法：item 的 slug 改成目標頁面的 slug，原本的名字如果跟目標標題不同，就加進別名。最後把落在同一個 slug 的 item 合併成一個（`_collapse()`）。

**(4) 摘要和 chunk 引用，平行進行**（`extract.py:196-204`）

摘要：

| | |
|---|---|
| prompt | `WIKI_SUMMARY_PROMPT` |
| 輸入 | 內文、語言、候選清單（`- [[slug]] = 名稱`，讓摘要可以直接連到這些頁面） |
| 輸出 | 純文字，第一行是 `SUMMARY: 一句話摘要`，後面是摘要頁內文 |
| 失敗時 | **整份 doc 失敗**，不寫進 state，下次執行會重試 |

chunk 引用（`_classify_citations()`，第 117 行）：

| | |
|---|---|
| prompt | `WIKI_CHUNK_CITATION_PROMPT` |
| 分批 | chunk 依序裝成每批最多 12000 字元，最多 4 批同時跑 |
| 輸入 | 候選清單、這批 chunk（用 `c000`、`c001` 這種臨時代號，避免 LLM 打錯真正的 ID） |
| 輸出 | JSON：`citations: {slug: [代號]}`，以及 `new_slugs`（Pass 0 漏掉、在 chunk 裡發現的新 item） |
| 失敗時 | 那一批當作沒有引用 |

**(5) 合併引用**（`_merge_citations()`，第 155 行）

- 每個 item 的 `source_chunks` 設成它被引用的 chunk。
- `new_slugs` 裡的新 item，slug 正規化後不和現有的重複，就加進 entities 或 concepts。

**(6) 產生 SlugUpdate**

- 1 個 `summary` 更新：slug 是 `summary/<doc 路徑去掉 .md 後 slugify>`（`summary_slug_for()`，第 35 行）。
- 每個 entity / concept 各 1 個更新，帶上 item 和這份 doc 的摘要當作背景。

**(7) 和上一版比對**（`extract.py:223-236`，只有 changed doc 才會有）

對 `old_slugs` 裡每個非摘要的頁面：

| 情況 | 產生的更新 | 要拿掉的內容 |
|---|---|---|
| 新版還提到這頁 | `retract` | 上一版的摘要內文（先拿掉舊貢獻，再由同一次 reduce 加上新貢獻） |
| 新版已經不提這頁 | `retractStale` | 這次的內文 |

### 7c. identity remap（`pipeline.py:79` `_remap_by_identity()`）

同一批的多份 doc 是平行處理的，同一個名字可能被不同 doc 轉成不同的 slug，例如中文名稱拼音化的方式不同。

- 依正規化後的名稱分組；
- 同組有多個 slug 時，選一個當正式的：已經存在的頁面優先，否則取字母序最小的；
- 把其他 slug 的更新搬過去，並改寫摘要內文裡的連結。

### 7d. taxonomy：分資料夾（`reduce.py:192` `plan_taxonomy()`）

只處理**還沒有分類**、而且這一批有新增內容的頁面。已經有分類的頁面不會被重新分類。

| | |
|---|---|
| prompt | `WIKI_TAXONOMY_PLAN_PROMPT` |
| 分批 | 每次最多 60 個 item |
| 輸入 | 現有的資料夾樹（從所有頁面的 `category` 收集，最多 150 條路徑）、item 清單（slug、標題、類型、前 120 字的描述） |
| 輸出 | JSON：`assignments: [{slug, path}]`，`path` 是由大到小的資料夾名稱 |
| 失敗時 | 那 60 個 item 這次沒有分類 |

輸出會被清理（`clean_category()`，第 163 行）：用 `/` 拆開、去掉空白和 `entity`、`concept` 這類類型名稱、去重複，最多 2 層。新的路徑會馬上加進現有資料夾樹，讓後面的批次沿用同一套分類。

WeKnora 在資料夾很多時，會用 embedding 相似度只挑相關的資料夾給 LLM。這裡不用 embedding，直接全部給（最多 150 條）。

### 7e. reduce：寫頁面（`reduce.py:46` `reduce_slug()`）

每個 slug 用 `ThreadPoolExecutor(reduce_parallel)` 平行處理，預設 8 個。每個 slug 會收到它在這一批的所有更新。

**摘要頁：不呼叫 LLM**

直接寫入：標題是 `<doc 標題> - Summary`，內文是 map 產生的摘要，`source_refs` 只有這份 doc。

**entity / concept 頁：呼叫一次 LLM**

1. **整理要刪的內容**（有 retract 時）：
   - `DeletedContent`：每個被 retract 的 doc 要拿掉的內容；
   - `RemainingSourcesContent`：其他還在的來源 doc 的摘要，讓 LLM 知道哪些事實還有其他出處、不能刪；
   - 從頁面的 `source_refs` 和 `chunk_refs` 拿掉這些 doc。
2. **整理要加的內容**（有新增時）：
   - `NewContent`：每份 doc 的 `**名稱**: 描述`，加上**被引用的 chunk 原文**；沒有引用時，改用 Pass 0 fallback 抽到的 `details`；
   - `SharedSourceContexts`：每份 doc 的摘要，當作背景；
   - 合併別名、加上來源 doc。
3. **只有 retract、而且沒有剩下任何來源** → 直接刪掉這頁，不呼叫 LLM。
4. **連結代號**（`links.py:75` `SlugHandles`）：現有內文裡的 `[[slug]]` 先換成 `ref-1`、`ref-2`，並列出 `AvailableSlugs`。LLM 只需要照抄代號，不會打錯真正的 slug。
5. 呼叫 LLM：

| | |
|---|---|
| prompt | system：`WIKI_PAGE_MODIFY_SYSTEM_PROMPT`；user：`WIKI_PAGE_MODIFY_USER_PROMPT` |
| 輸入 | 頁面 slug、標題、類型、別名、現有內文（新頁面是 `(New page)`）、上面整理的新增和刪除內容、語言 |
| 輸出 | 純文字，第一行 `SUMMARY: ...`，後面是整頁新內文 |
| 被截斷時 | `finish_reason` 是 `length` 就送 `WIKI_PAGE_MODIFY_CONTINUATION_PROMPT` 請它接著寫，最多 3 次；還是被截斷就當作失敗（`llm.py:205-222`） |
| 失敗時 | 頁面維持原樣，這個 slug 記為失敗 |

6. **寫回**：
   - 代號換回真正的 slug；
   - 拆出一行摘要和內文；
   - 加上新的 `chunk_refs`；
   - 還沒有分類就套用 7d 的結果；
   - `put_page()` 會更新 `updated_at`，`version` 加 1（`state.py:67-74`）。

### 7f. 收尾

- 每份 map 成功的 doc 寫進 `state.docs`（hash、標題、摘要）。**map 失敗的 doc 不會寫進去**，所以下次執行會被當成 added 或 changed，自動重試。
- 收集「這批有改到、而且沒失敗」的頁面 `(slug, 標題)`，給 finalize 加交叉連結用。
- 存 state。

---

## 8. finalize（`wikibuilder/finalize.py:98`）

所有批次跑完後只執行一次。

### 8.1 index 介紹（`rebuild_index_intro()`，第 30 行）

| 情況 | 做法 |
|---|---|
| 沒有任何摘要頁 | 介紹清空 |
| 還沒有介紹 | `WIKI_INDEX_INTRO_PROMPT`，輸入最近更新的最多 200 份 doc 摘要 |
| 已經有介紹，這次有變動 | `WIKI_INDEX_INTRO_UPDATE_PROMPT`，輸入現有介紹和這次新增、刪除的 doc（修改過的 doc 算新增） |
| 已經有介紹，沒有變動 | 不動 |

輸出只保留第一個 `## ` 標題之前的部分，後面的目錄由渲染時產生。第一次產生失敗的話，介紹留空，下次執行會重試。

### 8.2 清死連結（`clean_dead_links()`，第 65 行）

不呼叫 LLM。掃**所有頁面**，指向不存在頁面（或指向自己）的 `[[slug|文字]]` 換成純文字。WeKnora 只掃受影響的頁面，這裡全部掃一次，成本很低。

### 8.3 自動交叉連結（`inject_cross_links()`，第 79 行；`links.py:133` `linkify()`）

不呼叫 LLM。對這次受影響的頁面：

- 要找的對象：這頁已經連到的頁面，加上這次新增或改過的頁面，用它們的**標題**比對；
- 長的標題優先；這頁已經連過的 slug 不再加；
- 每個標題只把**第一個安全的出現位置**換成 `[[slug|標題]]`；
- 「安全」是指不在 code、既有連結、markdown 連結、網址、標題行裡面；英文字要符合單字邊界；
- 單一個中文字的標題不處理，避免誤連。

---

## 9. render（`wikibuilder/wiki_format.py`，`pipeline.py:185`）

`render_all()` 把 state 裡的頁面轉成 `{相對路徑: 檔案內容}`：

| 函式 | 做什麼 | 現在的預設 |
|---|---|---|
| `page_path()` | 檔案位置 | `<slug>.md`，例如 `entity/acme-corp.md` |
| `frontmatter()` | frontmatter 欄位 | `title`、`slug`、`type`、`summary`、`aliases`、`category`、`sources`、`source_chunks`、`links`、`created`、`updated`、`version` |
| `render_link()` | 連結語法 | 依 `config.yaml` 的 `format.link_style`：`wikilink` 或 `markdown`。目前 config 設成 `markdown` |
| `render_body()` | 內文 | 沒有 H1 就補上標題（`ensure_h1`）；可選加上來源清單（`sources_section`） |
| `render_index()` | `index.md` | 介紹 → `## Documents`（摘要頁）→ `## Directory`（entity / concept 依 `category` 分組，沒有分類的放在 `Uncategorized`） |

寫檔時：

- 只有內容有變的檔案才會重寫；
- 上次渲染過、這次沒有的檔案會被刪掉，空的資料夾也一起刪；
- **不會**碰 `wiki/` 裡其他不是它產生的檔案。

**分類只寫在 frontmatter 的 `category` 和 `index.md` 的目錄裡，檔案位置還是照 slug 放**，所以 `wiki/` 底下只會看到 `entity/`、`concept/`、`summary/`。原因和改法見 [`weknora-docker-comparison.md`](weknora-docker-comparison.md) 第 1、3 節。

---

## 10. LLM 呼叫層（`wikibuilder/llm.py`）

所有 LLM 呼叫都經過 `LLM.generate()` 或 `generate_json()`：

| 機制 | 說明 | 位置 |
|---|---|---|
| 並發上限 | 整個 build 共用一個 semaphore，`llm.max_concurrency`（預設 8） | `llm.py:127` |
| 重試 | 只重試暫時性錯誤：逾時、連線錯誤、429、5xx、408、409。額度用完（`insufficient_quota`）不重試。最多 `max_attempts`（預設 3）次，等待時間 2、4 秒 | `llm.py:134-176` |
| 業務指令 | `extraction_instructions` 附加到抽取類 prompt，`content_instructions` 附加到寫作類 prompt，包在 `<xxx_business_instructions>` 裡，並註明不能違反格式和事實規則 | `llm.py:36-47` |
| system / user | 只有頁面重寫用 system + user 兩則訊息，其他 prompt 都是一則 user 訊息 | `llm.py:195-203` |
| 圖片網址遮蔽 | 輸入裡的 markdown 圖片網址換成 `IMG_0001` 這種代號，輸出再換回來，避免 LLM 改壞網址 | `llm.py:50-66` |
| 續寫 | 只有頁面重寫會在被截斷時續寫，見 7e | `llm.py:205-222` |
| JSON 清理 | 去掉 ` ```json ` 外框；字串裡的真實換行轉成 `\n`；前後有多餘文字時，取第一個 `{` 到最後一個 `}` | `llm.py:69-107` |
| 紀錄 | 每次呼叫的 purpose、耗時、`finish_reason`、完整訊息和回應，寫進 `.wiki_state/llm_calls.jsonl` | `llm.py:178-187` |
| token 參數名稱 | 依 `llm.token_param` 送 `max_tokens` 或 `max_completion_tokens`；`temperature` 設成 `null` 就不送 | `llm.py:150-152` |

### 10.1 一次 build 大概會呼叫幾次 LLM

| 階段 | 次數 |
|---|---|
| Pass 0 | 每份 doc 1 次（失敗再加 1 次 fallback） |
| dedup | 每份 doc 最多 1 次（已經有頁面、而且有相似候選時才會呼叫） |
| 摘要 | 每份 doc 1 次 |
| chunk 引用 | 每份 doc 約「內文字數 ÷ 12000」次，至少 1 次（fallback 時 0 次） |
| taxonomy | 每批約「未分類 item 數 ÷ 60」次 |
| reduce | 每個被改到的 entity / concept 頁 1 次（被截斷時再加續寫次數）；摘要頁 0 次 |
| index 介紹 | 每次執行最多 1 次 |
| 死連結、交叉連結、render | 0 次 |

**reduce 通常是最大宗**：一份 doc 抽出 15 個 entity / concept，就是 15 次頁面重寫。

---

## 11. 失敗時會怎樣

| 失敗的地方 | 結果 | 下次執行 |
|---|---|---|
| Pass 0 | 改用 fallback 一次抽完，不做 chunk 引用 | — |
| fallback 也失敗、摘要失敗，或 map 裡其他例外 | 整份 doc 失敗，不寫進 `state.docs`，同批其他 doc 不受影響 | 自動重試 |
| dedup | 當作沒有合併，可能產生重複頁面 | 不會自動修正 |
| 某一批 chunk 引用 | 那批 chunk 不算進引用，頁面內容只靠其他引用或 `details` | 不會自動修正 |
| taxonomy | 那些頁面這次沒有分類 | 下次這些頁面有新內容時會再分類 |
| 頁面重寫 | 頁面維持原樣，不加進交叉連結的對象 | 不會自動重試；要等這頁之後又被更新，或用 `--rebuild` |
| index 介紹第一次產生 | 介紹留空，渲染時用預設標題 `# Wiki Index` | 自動重試 |
| 執行到一半中斷 | 已完成的批次都存在 state 裡 | 只處理還沒完成的 doc |

---

## 12. 設定（`config.yaml`）

| 設定 | 預設 | 影響 |
|---|---|---|
| `raw_dir` / `wiki_dir` / `state_dir` | `raw` / `wiki` / `.wiki_state` | 路徑，相對於 config 檔 |
| `include` | `["**/*.md"]` | 哪些檔案算 doc |
| `language` | `English` | 所有 prompt 的輸出語言 |
| `granularity` | `standard` | Pass 0 抽多少 entity / concept |
| `extraction_instructions` / `content_instructions` | 空白 | 附加到抽取類、寫作類 prompt 的業務指令 |
| `chunk_size` | `1000` | 每個 chunk 的字元上限 |
| `max_content_chars` | `32768` | 每份 doc 最多送多少字給 LLM |
| `docs_per_batch` | `5` | 一批幾個 op |
| `map_parallel` / `reduce_parallel` | `4` / `8` | map、reduce 的平行數 |
| `log_llm_calls` | `true` | 是否寫 `llm_calls.jsonl` |
| `llm.*` | — | `base_url`、`model`、`api_key_env`、`temperature`、`max_tokens`、`token_param`、`timeout`、`max_concurrency`、`extra_body` |
| `format.*` | — | 只影響 render，改完用 `--render-only` |

程式裡寫死的常數：

| 常數 | 值 | 位置 |
|---|---|---|
| 最少文字量 | 10 字元 | `extract.py:29` |
| 每批 chunk 引用的字數上限 | 12000 | `extract.py:30` |
| chunk 引用平行數 | 4 | `extract.py:31` |
| dedup 每個 item 的候選數、最低分數 | 5、0.08 | `dedup.py:22-23` |
| taxonomy 每次 item 數、資料夾上限、層數 | 60、150、2 | `reduce.py:20-22` |
| 頁面重寫最多續寫次數 | 3 | `llm.py:27` |
| index 介紹最多參考幾份摘要 | 200 | `finalize.py:18` |

---

## 13. 和 WeKnora 不一樣的地方

| 項目 | WeKnora | llm-wiki |
|---|---|---|
| 儲存 | Postgres（`wiki_pages`、`wiki_folders` 等表）+ Redis 任務佇列 | `.wiki_state/state.json` |
| 切 chunk | docreader 服務 | 自己用標題感知的規則切（`chunk_size`） |
| dedup 的相似度預篩 | pg_trgm | 記憶體內算字元 bigram Jaccard |
| taxonomy 挑資料夾 | 資料夾很多時用 embedding 相似度挑相關的 | 全部給 LLM，最多 150 條 |
| 分類存在哪 | `wiki_folders` 表，頁面用 `folder_id` 指過去；資料夾可以獨立改名、移動 | 頁面的 `category` 欄位；資料夾樹是從所有頁面收集出來的 |
| 清死連結的範圍 | 只有受影響的頁面 | 全部頁面 |
| retract 後沒有來源的頁面 | 留著，變成「(空頁面)」 | 直接刪除 |
| 執行方式 | 背景任務，文件上傳後自動觸發 | 手動執行 `build_wiki.py`，一次處理所有變動 |

這張表和 `README.md` 的「Deviations from WeKnora」一致，另外加上分類和執行方式兩項。
