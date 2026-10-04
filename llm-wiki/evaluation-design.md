# LLM-Wiki 品質評估設計書

> 狀態：Draft · 日期：2026-10-04 · 作者：rywang

---

## 1. 背景與問題

我們用 LLM 從一批**特定領域／私有文件語料**自動生成一個 wiki。語料來源眾多、數量龐大，生成出的 wiki 規模也很大（頁數多）。上線前需要一套方法來**驗證這個 wiki 的品質是否足夠好**，避免交付時出現亂編、漏東西、重複、壞結構等問題。

這份文件只定義**評估方法學與流程**，不含實作。

### 現況與限制

| 項目 | 狀況 | 對評估的影響 |
|---|---|---|
| 規模 | 來源多、wiki 大 | 無法全量人工檢查，必須抽樣 |
| 檢索器 | **沒有 retrieval** | 無法用檢索重找來源，事實查核改依賴 provenance |
| 參考答案 | 無 gold-standard wiki | 只能做 reference-free 評估 |
| 人力 | 有限 | 主力為 LLM-as-judge，人工僅用於校準 |
| 用途 | 上班交付，非學術 | 追求「抓到會出包的問題」，而非指標完美 |

### 關鍵前置依賴 ⚠️

**本評估的事實查核能否成立，取決於是否有 provenance（每頁 → 來源文件的對應記錄）。**
- 沒有檢索器，就只能靠生成時留下的來源對應，把「某頁 + 它的來源」一起交給 judge 做 self-contained 的查核。
- 若目前未記錄 provenance，**補上它是先決條件**，優先度高於任何指標設計。
- 詳見 [§9 待確認事項](#9-待確認事項與風險)。

---

## 2. 目標與非目標

### 目標
- 對整個 wiki 產出**可量化的品質估計**（而非逐頁全檢）。
- 能**定位弱點**：哪一類頁面、哪個維度特別差。
- 產出**可操作的壞頁清單**供修正。
- 成本可控、可重複、可隨 wiki 更新**增量重跑**。

### 非目標
- 不追求學術級嚴謹或與人類標註的高相關係數（只做基本校準）。
- 不做全量逐頁 LLM 檢查（成本不允許）。
- 不評估底層模型本身，只評估 wiki 產物。

---

## 3. 品質的定義：拆成正交維度

不使用單一「整體品質分」（噪音大、不可診斷）。改為拆成下列維度，各自用**可分解的二元判斷**聚合。

| # | 維度 | 問的問題 | 類比 | 方法 |
|---|---|---|---|---|
| D1 | **Faithfulness 事實正確性** | 頁面內容是否都有來源依據？有無亂編？ | precision | LLM-judge（頁+來源） |
| D2 | **Coverage 涵蓋度** | 來源的重點有沒有被漏掉？ | recall | LLM-judge（來源端抽樣） |
| D3 | **結構與完整性** | 空頁、斷連結、重複頁、孤兒頁 | — | 純程式，全量 |
| D4 | **可讀性／連貫性** | 組織、行文、是否自相矛盾 | — | LLM-judge + rubric |

D1、D2 是硬指標（可溯源，最有說服力）；D3 用程式全量掃（零成本、零噪音）；D4 最弱，僅供參考。

---

## 4. 評估架構：兩層 + 抽樣

### 第 1 層：全量廉價掃描（純程式，覆蓋 100%）

先用程式掃出所有「一眼可判定」的機械性問題，不需 LLM：

- **空頁 / stub**：字數過低（疑似生成失敗）。
- **斷連結**：內部 cross-link 指向不存在的頁。
- **孤兒頁**：沒有任何入連結的頁。
- **重複頁**：用 embedding 或 MinHash 偵測近乎重複的頁（大 wiki 最常見病症）。
- **格式異常**：異常長度、截斷、壞掉的 markdown。
- **Provenance 缺失**：沒掛到任何來源的頁（高風險，可能整頁是編的）。

> 此層預期可攔下多數明顯問題，且幾乎零成本，應在每次 wiki 更新後自動跑。

### 第 2 層：抽樣深度檢查（LLM-judge）

對第 1 層通過的頁面做**抽樣**，執行 D1 / D4；另對來源端抽樣執行 D2。不全跑。

---

## 5. 抽樣方法

目標是「對整體品質做有信心的估計」，不是逐頁檢查。

### 5.1 要抽多少？（與 wiki 大小無關）

這是最重要的一個觀念：**樣本數由你想要的誤差決定，而不是由 wiki 多大決定。** wiki 有 1,000 頁還是 100,000 頁，抽 150 頁得到的誤差幾乎一樣（母體夠大時，有限母體校正可忽略）。

比例估計的誤差公式：`誤差 e ≈ 1.96 × √(p(1−p)/n)`（95% 信心）。以我們預期品質偏高（p≈0.9）估算：

| 樣本數 n | 誤差（p≈0.9） | 最壞情況（p=0.5） |
|---|---|---|
| 100 | ±5.9% | ±9.8% |
| **150** | **±4.8%** | **±8.0%** |
| 200 | ±4.2% | ±6.9% |

**建議 n ≈ 150**，是成本與精度的甜蜜點。對上班交付足夠，報告可寫「D1 支持率 92% ± 5%」。

### 5.2 怎麼分層與分配（具體規則）

1. **選分層變數**：用 `來源數量` 分 3 桶：`1 份`、`2–5 份`、`6+ 份`。（可選再乘頁面長度三分位，但先別複雜化，3 桶就好。）
2. **各桶配額**：以「比例配置 + 下限」為基礎——
   - 每桶至少抽 **20 頁**（保證小桶也估得出來）。
   - 其餘名額按各桶頁數比例分配。
3. **高風險桶過度抽樣**：`6+ 份來源` 與 `最長的頁`這兩類，配額 ×2（問題通常集中在此）。
4. **桶內隨機抽**。
5. **回推整體要加權**：因為有過度抽樣，算全站總分時，**每桶的分數要用該桶的真實頁數比例加權**，不能直接平均（否則高風險桶會被灌水）。這點與 [§7](#7-產出與報告) 的綜合分數算法相關。

### 5.3 來源端抽樣（給 D2 用）

另隨機抽 **~30 份來源文件**，檢查其重點是否被 wiki 收錄。

---

## 6. 各維度評估協定

### D1 — Faithfulness（rubric 評分 + 證據）

不讓 LLM 自己去「數句子算比例」（denominator 模糊、不可靠）。改為**給它完整的評分標準（rubric），讓它輸出：分數 + 理由 + 佐證清單**。佐證清單同時扮演兩個角色：(a) 讓分數有依據（reasoning before scoring，比直接打分可靠）、(b) 直接變成待修正的幻覺清單。

**輸入**：抽樣頁面全文 + 其 provenance 對應的來源文件。

**評分標準（1–5，錨定描述）**：

| 分數 | 定義 |
|---|---|
| 5 | 全頁關鍵陳述皆可由來源支持，無任何無依據或矛盾內容。 |
| 4 | 絕大多數有依據，僅極少數無關緊要句子無法對應，且無事實矛盾。 |
| 3 | 多數有依據，但有少量**實質**內容無依據，或 1 處與來源矛盾。 |
| 2 | 多處實質內容無依據，或多處與來源矛盾。 |
| 1 | 大量內容無法對應來源，或嚴重與來源矛盾（疑似大段編造）。 |

**judge 輸出（結構化）**：
```json
{
  "score": 4,
  "justification": "為什麼給這個分數的簡短說明",
  "issues": [
    {"sentence": "原文句子", "type": "unsupported | contradiction", "reason": "..."}
  ]
}
```

- D1 指標 = 抽樣頁面的**平均分數**（依 §5.2 加權回推全站）。
- 所有 `type=contradiction` 的項目彙整成**幻覺清單**供修正。

> 原則：先列證據、再依 rubric 給分。分數不是 LLM 憑空給的印象分，而是對照明確標準、且有 issues 清單支撐的判斷。

**Judge prompt 範本（`{{SOURCE_DOCUMENTS}}`、`{{WIKI_PAGE}}` 為佔位符）**：

```text
You are a strict fact-checker. You are given SOURCE DOCUMENTS and a WIKI PAGE
that was generated from them. Judge whether every substantive statement in the
WIKI PAGE is supported by the SOURCE DOCUMENTS, then assign a score from 1 to 5.

Scoring rubric:
5 = Every key statement is supported by the source; no unsupported or contradicting content.
4 = Almost all statements are supported; only a few trivial, immaterial sentences cannot be mapped; no factual contradiction.
3 = Most statements are supported, but there is a small amount of substantive unsupported content, OR exactly one contradiction with the source.
2 = Multiple substantive statements are unsupported, OR multiple contradictions with the source.
1 = A large portion of the content cannot be mapped to the source, or severely contradicts it (likely fabricated).

Rules:
- Judge ONLY against the provided source documents. Do NOT use your own outside knowledge.
- "unsupported" = the source does not mention it; "contradiction" = the source states the opposite.
- Ignore commonsense connectives and pure paraphrase; flag only substantive facts.
- First list every problematic sentence (issues), THEN assign the score based on them.

<source_documents>
{{SOURCE_DOCUMENTS}}
</source_documents>

<wiki_page>
{{WIKI_PAGE}}
</wiki_page>

Output JSON only, no other text:
{"score": <1-5>, "justification": "<brief reason for the score>",
 "issues": [{"sentence": "<verbatim sentence>", "type": "unsupported|contradiction", "reason": "<why>"}]}
```

### D2 — Coverage（rubric 評分 + 證據）

**和 entailment 的關係**：D1 是「頁面的每句話是否被來源蘊含」（page ⊨ source，precision/查核亂編）；D2 是**反方向**——「來源的重點是否被 wiki 收錄」（source points ⊨ wiki，recall/查核漏失）。機制上每個重點都是一次「這個重點有沒有被 wiki 蘊含」的判斷，所以可說是反方向的 entailment。

**評分方式同 D1**：給 rubric，輸出分數 + 理由 + 漏失清單。

**輸入**：抽樣的來源文件 + 其對應的 wiki 頁面。

**評分標準（1–5）**：

| 分數 | 定義 |
|---|---|
| 5 | 來源所有重點都被 wiki 正確收錄。 |
| 4 | 絕大多數重點已收錄，僅漏極次要者。 |
| 3 | 主要重點大致收錄，但漏了少數重要重點。 |
| 2 | 漏掉多個重要重點。 |
| 1 | 大量重要重點未被收錄（涵蓋嚴重不足）。 |

**judge 輸出**：
```json
{
  "score": 3,
  "justification": "...",
  "missing_points": [{"point": "來源中的重點", "importance": "高|中|低"}]
}
```

- D2 指標 = 抽樣來源的**平均分數**。
- 「重要性」由 judge 在 rubric 內判斷（high/medium/low），並在報告寫明定義，屬方法學一部分。

**Judge prompt 範本（`{{SOURCE_DOCUMENT}}`、`{{WIKI_PAGE}}` 為佔位符）**：

```text
You are a strict coverage reviewer. You are given a SOURCE DOCUMENT and the
corresponding WIKI PAGE. Judge whether the key points of the SOURCE DOCUMENT are
captured in the WIKI PAGE, then assign a score from 1 to 5.

Scoring rubric:
5 = All key points of the source are correctly captured in the wiki.
4 = The vast majority of key points are captured; only very minor ones are missing.
3 = The main points are mostly captured, but a few important points are missing.
2 = Several important points are missing.
1 = A large portion of important points are not captured (severely incomplete).

Rules:
- A "key point" = an informative fact, definition, relationship, or conclusion in the source.
- For each missing point, label its importance (high/medium/low).
- Base the score mainly on whether IMPORTANT points are missing; minor omissions matter little.
- First list the missing points, THEN assign the score.

<source_document>
{{SOURCE_DOCUMENT}}
</source_document>

<wiki_page>
{{WIKI_PAGE}}
</wiki_page>

Output JSON only, no other text:
{"score": <1-5>, "justification": "<brief reason for the score>",
 "missing_points": [{"point": "<key point from source>", "importance": "high|medium|low"}]}
```

### D3 — 結構與完整性
全由第 1 層程式產出，無 LLM，已另有實作。評估時直接取用其結果（各類問題的頁數與比例），併入報告。

### D4 — 可讀性（單頁 rubric 評分）

是的，**只給 judge 單一頁面全文**（不需來源），評它自身讀起來好不好——組織性、行文連貫、是否自相矛盾。評分方式同 D1/D2（rubric + 理由 + 分數）。

| 分數 | 定義 |
|---|---|
| 5 | 結構清晰、層次分明、行文流暢，無冗贅、無自相矛盾，讀起來順暢。 |
| 4 | 整體清楚易讀，僅極少數小瑕疵（偶有冗句或段落銜接稍弱），無矛盾。 |
| 3 | 可讀，但組織鬆散、有明顯冗贅／重複，或有無傷大雅的小矛盾。 |
| 2 | 組織混亂或多處不連貫，閱讀吃力，或有明顯矛盾。 |
| 1 | 結構嚴重混亂、難以閱讀，或有嚴重自相矛盾。 |

D4 指標 = 抽樣頁面平均分數。此為最弱軸，僅輔助參考。

**Judge prompt 範本（`{{WIKI_PAGE}}` 為佔位符，不需來源）**：

```text
You are a document readability reviewer. You are given a single WIKI PAGE (no
source needed). Judge its own organization, flow/coherence, and whether it
contradicts itself, then assign a score from 1 to 5.

Scoring rubric:
5 = Clear structure, well-organized layers, fluent prose, no redundancy, no self-contradiction.
4 = Clear and readable overall, only a few minor flaws (occasional redundant sentence or weak transition), no contradiction.
3 = Readable, but loosely organized, noticeably redundant/repetitive, or with harmless minor contradictions.
2 = Disorganized or often incoherent, hard to read, or with clear contradictions.
1 = Severely disorganized, hard to read, or severely self-contradictory.

<wiki_page>
{{WIKI_PAGE}}
</wiki_page>

Output JSON only, no other text:
{"score": <1-5>, "justification": "<brief reason>", "issues": ["<readability problem>", "..."]}
```

---

## 7. 產出與報告

> 後續的「judge 可信度驗證（人工校準、注入錯誤的敏感度測試）」屬進階考量，本版先略，待方法跑通後再補。

評估的核心產出是**數字**：一個綜合分數 + 每個維度各一個分數。

### 7.1 每個維度一個分數

**為什麼 1–5 的評分可以變成連續百分比**：每個維度我們對 ~150 個樣本各打一個 1–5 的整數分，最終指標是**這些分數的平均**。單頁雖然只能是 1、2、3、4、5，但平均 150 筆之後就是連續值（如 4.23）——**粒度來自「樣本數」，而不是來自「把每頁打得更細」**。所以不需要 0–10 的細尺度，一樣能得到可做百分位、可比較、可畫趨勢的連續分數。

**正規化公式**（把 1–5 線性映射到 0–100%）：

```
百分比 = (平均分 − 1) / (5 − 1) × 100
```

分母是 `5 − 1 = 4`，因為最低分 1 代表 0%、最高分 5 代表 100%。
例：平均分 4.23 → `(4.23 − 1) / 4 × 100` = **80.75%**。

| 維度 | 原始分數 | 正規化到 0–100 |
|---|---|---|
| D1 Faithfulness | 抽樣頁面平均分（1–5），依 §5.2 加權 | `(分數−1)/4×100` |
| D2 Coverage | 抽樣來源平均分（1–5） | 同上 |
| D3 結構 | 乾淨頁比例（無任何結構紅旗） | `比例×100` |
| D4 可讀性 | 抽樣頁面平均分（1–5） | `(分數−1)/4×100` |

每個維度都附**信賴區間**（如 D1 = 82 ± 5）。

### 7.2 一個綜合分數

綜合分 = 各維度正規化分數的**加權平均**。權重是一個政策選擇，建議（事實正確性最重要）：

```
綜合分 = 0.40×D1 + 0.25×D2 + 0.20×D3 + 0.15×D4
```

> ⚠️ 綜合分方便一眼看趨勢，但會掩蓋細節——**報告一定要同時列出四個維度分數**，不能只給綜合分。例如 D1 很高但 D2 很低（沒亂編但漏一堆），綜合分看不出來。

### 7.3 報告其他內容

- **分層弱點**：哪一類頁面／維度最差（來自 §5.2 的分層結果）。
- **可操作清單**：壞頁清單、幻覺清單（D1 issues）、漏失重點清單（D2 missing_points）、結構問題清單（D3）。
- **趨勢**：與前次評估比較（wiki 更新後綜合分與各維度是否進步）。
- **通過門檻（gate）**：事先約定的上線標準（例如綜合分 ≥ N、D1 ≥ M）。

---

## 8. 執行流程（最小可行）

| 步驟 | 做法 | 覆蓋 | 成本 |
|---|---|---|---|
| 0 | 確認 provenance 的解析方式（見 §9） | — | 前置 |
| 1 | 取用既有結構掃描結果（D3） | 100% | ~0 |
| 2 | 分層抽 ~150 頁 → D1 + D4 | 抽樣 | 中 |
| 3 | 抽 ~30 份來源 → D2 | 抽樣 | 低 |
| 4 | 彙整報告：綜合分 + 四維度分 + 清單 | — | ~0 |

後續 wiki 更新時，D3 全量重跑、D1/D2 只重抽變動頁面所在的層（增量）。

---

## 9. 待確認事項與風險

- **Provenance 的格式與解析**：確認存在（✓ 已有），但**存放位置與格式待確認**——可能寫在每頁的 reference / related work 區塊內。需確定如何從 markdown 穩定解析出「這頁 → 哪些來源文件」，這是 D1/D2 能否自動跑的關鍵。
- **wiki 儲存格式**：✓ 為 markdown 檔。第 1 層掃描與 provenance 解析都以此為準。
- **單份來源是否過大？** 若單頁對應的來源集合太大塞不進 judge context，需考慮分段或只取 provenance 指到的段落。
- **「重要性」定義** 需與實際使用情境對齊（使用者最在意漏掉什麼）。
- **上線門檻** 綜合分與各維度的通過數字需與團隊約定。

---

## 10. 下一步

1. 確認 provenance 在 markdown 中的存放格式（§9 第一項），確定可穩定解析。
2. 設計 D1 judge 的 prompt（含 §6 的 rubric 與結構化輸出）與抽樣跑批腳本。
3. 跑一次小樣本（如 20 頁）驗證流程與 judge 輸出品質，再放大到 ~150 頁。
