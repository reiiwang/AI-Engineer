---
title: Segment-Based Vector Storage and Compaction
slug: concept/segment-based-vector-storage-and-compaction
type: concept
summary: Segment-based vector storage writes vectors to a log, groups them into immutable segments, and compacts storage by merging small segments and removing deleted vectors.
aliases: []
category:
- Technology Concepts
sources:
- cirrus-architecture.md
source_chunks:
- cirrus-architecture.md#c0000
links: []
created: '2026-10-13T14:39:01+00:00'
updated: '2026-10-13T14:39:01+00:00'
version: 1
---

# Segment-Based Vector Storage and Compaction

Vectors are written to an append-only write-ahead log, then grouped into immutable segments of up to 1 million vectors. A background compaction process merges small segments and removes deleted vectors.
