---
title: Payload Filtering
slug: concept/payload-filtering
type: concept
summary: Payload Filtering combines vector similarity searches with conditions on indexed fields attached to vectors, including language or category, and can restrict retrieval to documents users are allowed to see.
aliases:
- Metadata filtering
category:
- Technology Concepts
sources:
- cirrus-architecture.md
source_chunks:
- cirrus-architecture.md#c0000
- cirrus-architecture.md#c0002
links:
- entity/daniel-ortega
created: '2026-10-13T14:39:03+00:00'
updated: '2026-10-13T14:39:03+00:00'
version: 1
---

# Payload Filtering

Payload Filtering is a query technique that filters vector search results using indexed fields attached to vectors, such as language or category. Vectors can carry JSON payloads, and indexed payload fields allow queries to combine vector similarity with filters such as `category = "shoes"`.

```python
hits = client.search(
    collection="docs",
    vector=embedding,
    limit=5,
    filter={"lang": "en"},
)
```

[Daniel Ortega](../entity/daniel-ortega.md) has argued that payload filtering is the feature RAG users rely on most, because it lets applications restrict retrieval to documents a user is allowed to see.
