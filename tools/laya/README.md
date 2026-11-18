# Laya headline scorer

Scores market headlines with [Laya](https://github.com/receptron/laya), a small decision model that runs locally through ONNX (no API key; headlines never leave the machine).
`scripts/ingest_news.py` calls `node score.mjs` after each news fetch (`algo/data/news_laya.py`), and the result is stored beside the keyword reading in `news_item`.

Setup on a new machine (prod too): Node 20 or newer, then `npm install` in this folder. The first run downloads the model, about 1.7 GB, into `~/.cache/receptron-laya` and needs about 2 GB of memory; it takes minutes at a slow connection, so run it once by hand
(`echo '[{"id":"a","text":"Nifty hits a record high"}]' | node score.mjs`) before the first scheduled news job. Until the model is there, the job logs "laya: not scored" and the portal shows the keyword reading.

How it reads a headline: a three-way choice (negative / neutral / positive) and two yes/no questions (will this push prices up, will it push them down), averaged to -1..+1. On 38 headlines labelled by hand this agreed 82% of the time, against 74% for the keyword list and 61% for a single five-step rubric (TODO 6.14). Small and self-labelled: treat it as better, not proven.
