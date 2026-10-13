---
title: Retrieval-Augmented Generation
slug: concept/retrieval-augmented-generation
type: concept
summary: Retrieval-Augmented Generation retrieves relevant information or document passages and supplies them as context to a language model, with pipelines embedding questions and filtering which documents are retrieved.
aliases:
- RAG
category:
- Technology Concepts
sources:
- cirrus-architecture.md
- nimbus-labs-overview.md
source_chunks:
- cirrus-architecture.md#c0002
- nimbus-labs-overview.md#c0003
links:
- entity/daniel-ortega
created: '2026-10-13T14:39:03+00:00'
updated: '2026-10-13T14:39:03+00:00'
version: 1
---

# Retrieval-Augmented Generation

Retrieval-Augmented Generation (RAG) is an approach in which an application retrieves relevant information or document passages and provides them as context to a large language model when generating a response.

## Use in RAG pipelines

Documents are split into chunks, each chunk is embedded, and the embeddings are stored in a collection. At question time, the application embeds the question, retrieves matching chunks, and passes them to the language model.

[Daniel Ortega](../entity/daniel-ortega.md) has argued that payload filtering is the feature RAG users rely on most, because it lets applications restrict retrieval to documents a user is allowed to see.
