---
title: Index
type: index
---

# AI Data Infrastructure

This wiki covers Nimbus Labs’ company, products, customers, and business model, alongside Cirrus 3.2’s storage, indexing, query, retrieval, and deployment architecture. It also summarizes benchmark results and the role of filters in retrieval workflows.

## Documents

- [Cirrus Architecture Notes - Summary](summary/cirrus-architecture.md) — This page summarizes Cirrus 3.2’s storage, indexing, query, retrieval, and deployment architecture, including benchmark results and the role of filters in retrieval workflows.
- [Nimbus Labs Company Overview - Summary](summary/nimbus-labs-overview.md) — This overview describes Nimbus Labs’ founding, growth, products, customer use cases, revenue model, and leadership in AI-focused data infrastructure.

## Directory

### Organizations

- [Nimbus](entity/nimbus.md) — Nimbus is the organization that develops Cirrus, an open-source vector database described in the architecture notes.
- [Nimbus Labs](entity/nimbus-labs.md) — Nimbus Labs is a Taipei-founded infrastructure software company focused on data infrastructure for AI, with products Cirrus and Cirrus Cloud and more than 600 reported paying customers.

### People

- [Daniel Ortega](entity/daniel-ortega.md) — Daniel Ortega is a co-founder and CTO of Nimbus Labs, where he leads the core database engineering team; he previously researched approximate nearest neighbor indexes.
- [Lin Mei-Hua](entity/lin-mei-hua.md) — Lin Mei-Hua is a co-founder and CEO of Nimbus Labs, with prior experience leading search infrastructure at a large e-commerce company.
- [Priya Raman](entity/priya-raman.md) — Priya Raman is Nimbus Labs’ VP of Engineering, a role she has held since 2022, and is responsible for Cirrus Cloud reliability.

### Software Products

- [Cirrus](entity/cirrus.md) — Cirrus is an open-source vector database for low-latency approximate nearest neighbor search, with collection-based storage, HNSW indexing, payload filters, and single-node or clustered deployment.
- [Cirrus Cloud](entity/cirrus-cloud.md) — Cirrus Cloud is Nimbus Labs’ commercially licensed, fully managed Cirrus service, launched in 2024, with the same engine, automatic scaling, backups, and usage-based pricing.

### Technology Concepts

- [Hierarchical Navigable Small World](concept/hierarchical-navigable-small-world.md) — Hierarchical Navigable Small World is a layered graph method for approximate nearest neighbor search, navigating from sparse upper layers to denser lower layers with parameters that trade off recall, speed, and memory.
- [Payload Filtering](concept/payload-filtering.md) — Payload Filtering combines vector similarity searches with conditions on indexed fields attached to vectors, including language or category, and can restrict retrieval to documents users are allowed to see.
- [Retrieval-Augmented Generation](concept/retrieval-augmented-generation.md) — Retrieval-Augmented Generation retrieves relevant information or document passages and supplies them as context to a language model, with pipelines embedding questions and filtering which documents are retrieved.
- [Segment-Based Vector Storage and Compaction](concept/segment-based-vector-storage-and-compaction.md) — Segment-based vector storage writes vectors to a log, groups them into immutable segments, and compacts storage by merging small segments and removing deleted vectors.
- [Vector Database](concept/vector-database.md) — A vector database stores and searches vector representations, enabling similarity search across documents and other unstructured data.
