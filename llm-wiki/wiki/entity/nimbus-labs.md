---
title: Nimbus Labs
slug: entity/nimbus-labs
type: entity
summary: Nimbus Labs is a Taipei-founded infrastructure software company focused on data infrastructure for AI, with products Cirrus and Cirrus Cloud and more than 600 reported paying customers.
aliases: []
category:
- Organizations
sources:
- nimbus-labs-overview.md
source_chunks:
- nimbus-labs-overview.md#c0000
- nimbus-labs-overview.md#c0001
- nimbus-labs-overview.md#c0002
- nimbus-labs-overview.md#c0003
- nimbus-labs-overview.md#c0004
links:
- entity/nimbus
- entity/lin-mei-hua
- entity/daniel-ortega
- entity/cirrus
- entity/cirrus-cloud
- concept/retrieval-augmented-generation
- entity/priya-raman
created: '2026-10-13T14:39:03+00:00'
updated: '2026-10-13T14:39:03+00:00'
version: 1
---

# Nimbus Labs

[Nimbus](nimbus.md) Labs is a fictional infrastructure software company founded in Taipei in 2019 by [Lin Mei-Hua](lin-mei-hua.md) and [Daniel Ortega](daniel-ortega.md). It builds data infrastructure for AI applications, focusing on search over unstructured data. The company employs about 140 people across offices in Taipei and Berlin.

## History

Lin Mei-Hua previously led the search infrastructure team at a large e-commerce company, where she encountered the limits of keyword search for product discovery. Daniel Ortega was a database researcher working on approximate nearest neighbor indexes. They started Nimbus Labs in 2019 to turn that research into a product.

- **2019:** Founded; raised a USD 4 million seed round.
- **2021:** Released [Cirrus](cirrus.md), the company’s vector database.
- **2023:** Raised a USD 38 million Series B led by Northwind Ventures and opened a Berlin office.
- **2024:** Launched [Cirrus Cloud](cirrus-cloud.md), a managed version of Cirrus.

## Products

| Product | Description | License |
|---|---|---|
| Cirrus | Open-source vector database for similarity search | Apache 2.0 |
| Cirrus Cloud | Fully managed Cirrus service with usage-based pricing | Commercial |

Most of Nimbus Labs’ revenue comes from Cirrus Cloud. The open-source Cirrus project is the main adoption channel: teams start by self-hosting and later move to the managed service.

## Customers and use cases

Nimbus Labs reports more than 600 paying customers. Its most common use case is [Retrieval-Augmented Generation](../concept/retrieval-augmented-generation.md) (RAG), where an application retrieves relevant documents from Cirrus and passes them to a large language model as context. Other use cases include product recommendation and duplicate image detection.

## Leadership

- **Lin Mei-Hua:** Co-founder and CEO; responsible for product direction and go-to-market.
- **Daniel Ortega:** Co-founder and CTO; leads the core database engineering team.
- **[Priya Raman](priya-raman.md):** VP of Engineering since 2022, previously at a cloud storage company; owns Cirrus Cloud reliability.
