# Scrapy Observability — PaZuFa Stats Counters

This document describes the custom Scrapy stats counters emitted by the PaZuFa scraper pipelines.

## Mechanism

All counters are implemented via `StatsPipeline`, a mixin base class that wraps Scrapy's built-in [stats collection](https://docs.scrapy.org/en/latest/topics/stats.html):

```python
class StatsPipeline(BasePipeline):
    def increment_stats(self: Self, counter: StatsCounter | str) -> None:
        ...
        self.stats.inc_value(counter.value)
```

Every counter key is automatically prefixed with `PaZuFa/`, so all custom metrics are grouped under that namespace and are easy to distinguish from Scrapy's built-in stats.

## Reading stats after a crawl

Scrapy prints all collected stats to the log at the end of each run:

```text
2026-05-31 12:00:00 [scrapy.statscollectors] INFO: Dumping Scrapy stats:
{
  'PaZuFa/Vorgang': 42,
  'PaZuFa/Vorgang/submit/accepted': 40,
  ...
}
```

## Counter reference

Counters are grouped by the data entity they track. Each section notes the responsible pipeline class and its priority in the pipeline chain.

### Vorgang

*Emitted across multiple pipelines.*

**Hierarchy:**

```text
PaZuFa/Vorgang/
├── total                                    ← total valid items
├── drop/
│   ├── incorrect                            ← parse failure
│   ├── out_of_scope                         ← outside wahlperiode scope
│   ├── no_documents                         ← build failure
│   └── no_stations                          ← build failure
└── submit/
    ├── attempt                              ← PUT sent
    ├── accepted                             ← HTTP 201
    ├── grace_period_error                   ← grace period exceeded on submit
    └── rejected/
        └── {status_code}                    ← dispatch by non-201 HTTP status (dynamic)
```

### Dokument

*Emitted by `DownloadDocuments`.*

One count per document URL processed.

**Hierarchy:**

```text
PaZuFa/Dokument/
├── url/
│   ├── missing_primary                      ← primary url missing, using additional
│   ├── recovered_primary_from_additional    ← primary restored from additional url
│   └── pruned_addtional                     ← additional url pruned as duplicate
├── cache/
│   ├── hit                                  ← served from cache
│   ├── miss                                 ← cache cold, download needed
│   └── reset                                ← cache invalidated
└── download/
    ├── done                                 ← success
    └── failed/
        ├── incorrect_response               ← bad response body type
        └── incorrect_status                 ← non-200 HTTP status
```

### Text

*Emitted by `ExtractText`.*

One count per document URL processed.

**Hierarchy:**

```text
PaZuFa/Text/
├── cache/
│   ├── hit                                  ← served from cache
│   └── miss                                 ← cache cold, extraction needed
└── extract/
    ├── done                                 ← success
    └── failed/
        ├── empty_text                       ← empty extraction result
        └── not_plain_text                   ← extraction result not plain text
```

### LLM + Summary

*Emitted by `SummarizeText`.*

One count per document URL processed.

**Hierarchy:**

```text
PaZuFa/
├── Summary/
│   ├── ignore                               ← ignore summary for this Dokument
│   └── cache/
│       ├── hit                              ← served from cache
│       └── miss                             ← cache cold, LLM call needed
└── LLM/
    ├── extract_relevant_section/
    │   ├── total                            ← total attempts to extract relevant section using LLM
    │   ├── done                             ← success
    │   └── failed                           ← failed
    └── summarize/
        ├── {art_l}                          ← dispatch by document type (dynamic)
        ├── total                            ← total summarize attempts
        ├── done                             ← success
        └── failed/
            ├── provider                     ← LLM provider error
            ├── application                  ← summarize() returned None
            ├── empty_summary                ← empty LLM output
            └── not_plain_text               ← non-plain-text LLM output
```
