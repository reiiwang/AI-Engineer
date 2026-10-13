# Cirrus Architecture Notes

Cirrus is the open-source vector database developed by Nimbus. It stores high-dimensional embedding vectors and answers approximate nearest neighbor (ANN) queries with low latency. This note describes the internal architecture as of Cirrus 3.2.

## Storage model

Data in Cirrus is organized into **collections**. Each collection has a fixed vector dimension and a distance metric (cosine, dot product, or Euclidean). Vectors are written to an append-only write-ahead log first, then grouped into immutable **segments** of up to 1 million vectors. A background compaction process merges small segments and removes deleted vectors.

Each vector can carry a JSON payload. Payload fields can be indexed so that queries can combine vector similarity with filters such as `category = "shoes"`.

## Indexing with HNSW

Cirrus uses Hierarchical Navigable Small World (HNSW) graphs as its default index. HNSW builds a multi-layer graph in which upper layers contain few nodes with long-range links and lower layers contain all nodes with short-range links. A search starts at the top layer and greedily moves closer to the query vector at each layer.

Two parameters control the trade-off between recall, speed, and memory:

- `M`: the maximum number of links per node. Cirrus defaults to 16.
- `ef_search`: the size of the candidate list during search. Cirrus defaults to 64; higher values improve recall but increase latency.

In the team's internal benchmark on 10 million 768-dimensional vectors, Cirrus 3.2 reached 0.97 recall@10 with a p99 latency of 12 ms on a single node.

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

Cirrus is commonly used as the retrieval layer in RAG systems. Documents are split into chunks, each chunk is embedded, and the embeddings are stored in a Cirrus collection. At question time the application embeds the question, retrieves the top matching chunks, and passes them to the language model. Daniel Ortega has argued that payload filtering is the feature RAG users rely on most, because it lets applications restrict retrieval to documents a user is allowed to see.

## Deployment

Cirrus runs as a single binary. A cluster shards collections across nodes and keeps two replicas of each shard by default. Cirrus Cloud runs the same engine and adds automatic scaling, backups, and a usage-based billing layer.
