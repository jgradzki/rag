# Retrieval-Augmented Generation (RAG) — an Introduction

## What is RAG

Retrieval-Augmented Generation (RAG) is a technique that connects a large language model (LLM) to an external knowledge base. Instead of relying only on the knowledge stored in the model's weights during training, a RAG system first searches for document fragments relevant to the question and then passes them to the model as context. The model generates its answer based on those fragments.

The term was popularised in 2020 by a paper from Facebook AI Research (Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks").

## Why use RAG

- **Freshness** — the document base can be updated at any time without retraining the model.
- **Private data** — the model can answer questions about internal documents it never saw during training.
- **Fewer hallucinations** — the model answers from the provided text rather than "from memory".
- **Verifiability** — answers can cite their sources, which the user can check.
- **Cost** — RAG is much cheaper than fine-tuning a model on your own data.

## How it works

### 1. Indexing (offline)

1. **Loading documents** — PDF files, Markdown, web pages etc. are converted to plain text.
2. **Chunking** — the text is split into fragments (chunks), usually 500–1500 characters long, with a small overlap so that sentences on chunk boundaries are not lost.
3. **Embedding** — each chunk is turned into a vector of numbers by an embedding model. Chunks with similar meaning get vectors that lie close to each other.
4. **Storing in a vector database** — vectors, together with the text and metadata, go into a database such as Chroma, Qdrant, pgvector or Pinecone.

### 2. Answering a question (online)

1. The user's question is turned into a vector with the same embedding model.
2. The vector database returns the k most similar chunks (usually k = 3–10), most often ranked by cosine similarity.
3. The chunks are inserted into the prompt together with the question and an instruction to answer only from them.
4. The LLM generates the answer, ideally with citations pointing to the chunks it used.

## Common problems and improvements

- **Wrong chunk size** — chunks that are too small lose context; chunks that are too large blur the meaning of the vector.
- **Ambiguous questions** — query rewriting or generating several variants of the question helps.
- **Keywords and proper names** — vector search struggles with product codes or surnames; the fix is hybrid search (vectors + BM25 keyword search).
- **Result ordering** — a re-ranking model (cross-encoder) can re-score the retrieved chunks and improve their order.
- **Evaluation** — RAG quality is measured separately for retrieval (were the right chunks found?) and generation (is the answer faithful to the sources?). Popular tools include RAGAS and DeepEval.
