---
title: Cirrus Architecture Notes - Summary
slug: summary/cirrus-architecture
type: summary
summary: This page summarizes Cirrus 3.2’s storage, indexing, query, retrieval, and deployment architecture, including benchmark results and the role of filters in retrieval workflows.
aliases: []
category: []
sources:
- cirrus-architecture.md
source_chunks: []
links:
- entity/cirrus
- entity/nimbus
- concept/segment-based-vector-storage-and-compaction
- concept/payload-filtering
- concept/hierarchical-navigable-small-world
- concept/retrieval-augmented-generation
- entity/daniel-ortega
- entity/cirrus-cloud
created: '2026-10-13T14:38:55+00:00'
updated: '2026-10-13T14:38:55+00:00'
version: 1
---

# Cirrus Architecture Notes - Summary

## Overview

[Cirrus](../entity/cirrus.md) is an open-source vector database developed by [Nimbus](../entity/nimbus.md). As of version 3.2, it stores high-dimensional embedding vectors and supports low-latency approximate nearest neighbor (ANN) searches. Its architecture combines append-only writes, immutable storage segments, graph-based indexing, and filtering over JSON payloads.

## Storage and collections

Data is organized into collections. Each collection has a fixed vector dimension and uses one distance metric: cosine, dot product, or Euclidean distance.

Writes first go to an append-only write-ahead log. They are then grouped into immutable segments, each containing up to one million vectors. A background process merges smaller segments and removes deleted vectors. This approach is described as [Segment-Based Vector Storage and Compaction](../concept/segment-based-vector-storage-and-compaction.md).

Vectors may also include JSON payloads. Payload fields can be indexed to support [Payload Filtering](../concept/payload-filtering.md), allowing similarity searches to be combined with conditions such as `category = "shoes"`.

## Indexing and search

[Cirrus](../entity/cirrus.md) uses [Hierarchical Navigable Small World](../concept/hierarchical-navigable-small-world.md) (HNSW) graphs as its default index. HNSW organizes vectors in multiple graph layers: upper layers have fewer nodes and longer-range links, while the bottom layer contains all nodes and shorter-range links. A search begins at the top and greedily moves toward vectors closer to the query at each layer.

Two parameters balance recall, speed, and memory:

- **`M`** sets the maximum number of links per node. The default is **16**.
- **`ef_search`** sets the size of the candidate list considered during search. The default is **64**. Increasing it can improve recall, but also increases latency.

In an internal benchmark on a single node, [Cirrus](../entity/cirrus.md) 3.2 achieved **0.97 recall@10** with **12 ms p99 latency** on 10 million vectors of 768 dimensions.

## Query example

The Python client searches a named collection, using a query vector, a result limit, and an optional filter:

```python
from cirrus import Client

client = Client("http://localhost:6333")
hits = client.search(
    collection="docs",
    vector=embedding,
    limit=5,
    filter={"lang": "en"},
)
```

## Use in retrieval workflows

[Cirrus](../entity/cirrus.md) is commonly used as the retrieval layer in [Retrieval-Augmented Generation](../concept/retrieval-augmented-generation.md) systems. Documents are split into chunks, the chunks are embedded and stored in a collection, and questions are embedded at query time. The application retrieves the most relevant chunks and passes them to a language model.

[Daniel Ortega](../entity/daniel-ortega.md) argues that [Payload Filtering](../concept/payload-filtering.md) is the feature retrieval users rely on most, because it lets applications limit results to documents a user is authorized to access. This illustrates how payload conditions can support access-aware retrieval alongside vector similarity.

## Deployment

[Cirrus](../entity/cirrus.md) runs as a single binary. In a cluster, collections are sharded across nodes, with two replicas of each shard by default. [Cirrus Cloud](../entity/cirrus-cloud.md) uses the same engine and adds automatic scaling, backups, and usage-based billing.

## Key Takeaways

- Collections define a fixed vector dimension and distance metric; writes flow through a log into immutable segments that are compacted in the background.
- HNSW is the default index, with `M` and `ef_search` controlling important recall, speed, and memory trade-offs.
- The reported single-node benchmark reached 0.97 recall@10 at 12 ms p99 latency for 10 million 768-dimensional vectors.
- Payload indexes enable filtered similarity search and are particularly useful for access-aware retrieval workflows.
- Cluster deployments shard collections and default to two replicas per shard; the cloud service adds managed operational and billing features.
