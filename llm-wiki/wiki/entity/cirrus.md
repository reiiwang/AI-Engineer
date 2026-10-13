---
title: Cirrus
slug: entity/cirrus
type: entity
summary: Cirrus is an open-source vector database for low-latency approximate nearest neighbor search, with collection-based storage, HNSW indexing, payload filters, and single-node or clustered deployment.
aliases: []
category:
- Software Products
sources:
- cirrus-architecture.md
- nimbus-labs-overview.md
source_chunks:
- cirrus-architecture.md#c0000
- cirrus-architecture.md#c0001
- cirrus-architecture.md#c0002
- cirrus-architecture.md#c0003
- nimbus-labs-overview.md#c0001
- nimbus-labs-overview.md#c0002
- nimbus-labs-overview.md#c0003
links:
- entity/nimbus
- concept/hierarchical-navigable-small-world
- concept/retrieval-augmented-generation
- entity/daniel-ortega
- entity/cirrus-cloud
created: '2026-10-13T14:39:06+00:00'
updated: '2026-10-13T14:39:06+00:00'
version: 1
---

# Cirrus

Cirrus is [Nimbus](nimbus.md)’s open-source vector database for similarity search, released in 2021 under the Apache 2.0 license. As of version 3.2, it stores high-dimensional embedding vectors and supports low-latency approximate nearest neighbor (ANN) queries.

## Storage model

Data in Cirrus is organized into collections. Each collection has a fixed vector dimension and a distance metric: cosine, dot product, or Euclidean. Vectors are written to an append-only write-ahead log, then grouped into immutable segments of up to one million vectors. A background compaction process merges small segments and removes deleted vectors.

Each vector can carry a JSON payload. Payload fields can be indexed so queries can combine vector similarity with filters such as `category = "shoes"`.

## Indexing with HNSW

Cirrus uses [Hierarchical Navigable Small World](../concept/hierarchical-navigable-small-world.md) (HNSW) graphs as its default index. HNSW builds a multi-layer graph in which upper layers contain few nodes with long-range links and lower layers contain all nodes with short-range links. A search starts at the top layer and greedily moves closer to the query vector at each layer.

Two parameters control the trade-off between recall, speed, and memory:

- **`M`** sets the maximum number of links per node. Cirrus defaults to **16**.
- **`ef_search`** sets the size of the candidate list during search. Cirrus defaults to **64**; higher values improve recall but increase latency.

In the team’s internal benchmark on 10 million 768-dimensional vectors, Cirrus 3.2 reached **0.97 recall@10** with **12 ms p99 latency** on a single node.

## Query example

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

## Use in RAG pipelines

Cirrus is commonly used as the retrieval layer in [Retrieval-Augmented Generation](../concept/retrieval-augmented-generation.md) (RAG) systems. Documents are split into chunks, each chunk is embedded, and the embeddings are stored in a Cirrus collection. At question time, the application embeds the question, retrieves the top matching chunks, and passes them to the language model.

[Daniel Ortega](daniel-ortega.md) has argued that payload filtering is the feature RAG users rely on most, because it lets applications restrict retrieval to documents a user is allowed to see.

## Deployment

Cirrus runs as a single binary. A cluster shards collections across nodes and keeps two replicas of each shard by default. [Cirrus Cloud](cirrus-cloud.md) runs the same engine.
