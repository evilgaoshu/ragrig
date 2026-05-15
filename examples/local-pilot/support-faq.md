# RAGRig Local Pilot Support FAQ

## Does the demo require a cloud model?

No. The startup path should work without cloud API keys. Gemini, OpenAI, and
OpenRouter can be added later for live answer checks, but missing keys should be
reported as optional readiness, not a startup failure.

## What should I check after uploading documents?

Open the pipeline run summary and confirm that parsing, chunk creation, embedding,
and indexing completed. Then open the chunk preview and verify that the uploaded
handbook or FAQ text appears with the source file name.

## What makes an answer trustworthy?

A trustworthy Local Pilot answer is grounded. It should cite evidence chunks from
the uploaded source documents, include citation metadata, and make it clear which
document supported the response.

## Which model path is recommended first?

Use Ollama or LM Studio locally when possible. If a team already has cloud access,
Gemini, OpenAI, or OpenRouter can be configured after the basic local startup path
is healthy.
