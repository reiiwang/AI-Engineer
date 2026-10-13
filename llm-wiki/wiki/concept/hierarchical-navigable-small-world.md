---
title: Hierarchical Navigable Small World
slug: concept/hierarchical-navigable-small-world
type: concept
summary: Hierarchical Navigable Small World is a layered graph method for approximate nearest neighbor search, navigating from sparse upper layers to denser lower layers with parameters that trade off recall, speed, and memory.
aliases:
- HNSW
category:
- Technology Concepts
sources:
- cirrus-architecture.md
source_chunks:
- cirrus-architecture.md#c0001
links:
- entity/cirrus
created: '2026-10-13T14:39:03+00:00'
updated: '2026-10-13T14:39:03+00:00'
version: 1
---

# Hierarchical Navigable Small World

Hierarchical Navigable Small World (HNSW) is a layered graph indexing method for approximate nearest neighbor search that navigates from sparse upper layers to denser lower layers.

## Indexing with HNSW

HNSW builds a multi-layer graph in which upper layers contain few nodes with long-range links and lower layers contain all nodes with short-range links. A search starts at the top layer and greedily moves closer to the query vector at each layer.

Two parameters control the trade-off between recall, speed, and memory:

- `M`: the maximum number of links per node. [Cirrus](../entity/cirrus.md) defaults to 16.
- `ef_search`: the size of the candidate list during search. Cirrus defaults to 64; higher values improve recall but increase latency.
