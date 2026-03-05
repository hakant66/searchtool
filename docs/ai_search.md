# AI Search Pipeline

## Overview

The app uses a hybrid pipeline so it remains usable even when OpenAI is unavailable.

1. **Exact binary check**  
   Query image SHA-256 is compared against indexed image SHA-256 values.
2. **Visual similarity prefilter**  
   Query image pHash is compared against indexed pHash values and top candidates are selected.
3. **Vision cosine rerank (when AI semantic toggle is enabled)**  
   - query image is converted to a local vision embedding (`vision-local-rgbgray-v1`)
   - indexed image vision embeddings are cosine-ranked
   - final score blends visual hash score and vision cosine score
4. **Explainability text (optional)**  
   If `OPENAI_API_KEY` is present, `gpt-4o` generates a concise image description for UI display.

## Embeddings storage

Embeddings are stored in SQLite table `embeddings`:

- `file_id` (with model as composite key)
- `model`
- `vector` (float32 blob)
- `dims`
- `updated_at`

Vision embeddings are stored in SQLite table `vision_embeddings`:

- `file_id` (with model as composite key)
- `model`
- `vector` (float32 blob)
- `dims`
- `updated_at`

## Indexing behavior

During indexing, item text is built from metadata/path/filename and embedded with
`text-embedding-3-small` when AI is enabled. Embeddings refresh when:

- the file content changes
- metadata-derived fields change
- no existing embedding is found for the item+model

During indexing, every image also gets a local vision embedding for image rerank.

## Fallback behavior

If OpenAI key is missing, invalid, or a network call fails:

- indexing continues (text embeddings skipped when OpenAI disabled)
- image search still returns SHA-256/pHash + local vision cosine rerank
- text search still supports keyword FTS mode
