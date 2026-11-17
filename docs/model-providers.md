# Model provider configuration

## Compatibility contract

Argumentum sends requests to:

```text
POST <ARGUMENTUM_LLM_BASE_URL>/chat/completions
```

The endpoint should accept a JSON body with `model`, `temperature`, `response_format: {"type": "json_object"}`, and chat `messages`, and return the conventional `choices[0].message.content` shape. The provider adapter supports either a string message body or a list of text content parts.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARGUMENTUM_LLM_BASE_URL` | Base URL, without `/chat/completions`. | `https://api.openai.com/v1` |
| `ARGUMENTUM_LLM_API_KEY` | Provider key. | Empty |
| `OPENAI_API_KEY` | Fallback key if Argumentum key is absent. | Empty |
| `ARGUMENTUM_LLM_MODEL` | Model name accepted by endpoint. | `gpt-4.1-mini` |
| `ARGUMENTUM_TIMEOUT_SECONDS` | Per-request timeout. | `90` |
| `ARGUMENTUM_MAX_RETRIES` | Number of retries after retryable failures. | `2` |
| `OPENALEX_API_KEY` | Optional OpenAlex API key. | Empty |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional Semantic Scholar Graph API key. | Empty |
| `ARGUMENTUM_MAILTO` | Optional contact email for scholarly API identification/polite-pool use. | Empty |
| `ARGUMENTUM_GROBID_URL` | Optional private GROBID base URL for researcher-supplied PDF extraction. | Empty |
| `ARGUMENTUM_GROBID_TIMEOUT_SECONDS` | GROBID request timeout. | `180` |

The `.env.example` file is a template only; Python does not automatically load `.env`. Export variables in your shell or use a managed secret/environment tool. Never commit real `.env` files or API keys.

## Hosted providers

Set the provider's official base URL, a supported model identifier, and a key with permission to call its chat-completions endpoint. Not all providers support JSON response mode in the same way. A model may return syntactically valid but semantically incomplete JSON; inspect every stage output.

## Local inference

Any local service that implements the expected OpenAI-compatible request/response contract may work. Point `ARGUMENTUM_LLM_BASE_URL` at the local server and set the model name it exposes. A local endpoint may not require a key. Keep it bound to loopback unless the deployment is authenticated and network-isolated.

## Request privacy

Every model call includes the research question, relevant source records, prior agent outputs, and bounded excerpts of input materials needed by that stage. The exact context differs by agent. Hosted services may process or retain these inputs according to their contractual terms. Argumentum does not anonymize the material, encrypt it at rest, or guarantee provider-side zero retention. Evaluate data governance before use.

## Scholarly retrieval and document extraction

Five read-only discovery adapters are available: OpenAlex, Crossref, Semantic Scholar, Europe PMC, and arXiv. The adapters normalize records and deduplicate primarily by DOI, with a conservative title/year/first-author fallback when DOI is absent. Metadata coverage, abstracts, rate limits, and ranking differ by provider. Discovery is not equivalent to comprehensive systematic searching.

For full-text structure extraction of user-supplied PDFs, an operator may start the GROBID Compose profile and set `ARGUMENTUM_GROBID_URL=http://grobid:8070`. GROBID's `/api/processFulltextDocument` endpoint returns TEI XML; Argumentum extracts selected article sections and references with size bounds, then falls back to `pypdf` text extraction if GROBID is unavailable. The extracted references are not automatically verified or deemed citable. See [Self-hosting and operations](self-hosting.md).

## Cost and latency

A full run uses ten sequential model calls in this implementation, plus scholarly API calls. Total tokens and cost depend on model, result count, abstracts, input size, and provider billing. Token usage is included in the run manifest only when the endpoint returns it. Argumentum does not estimate price because provider tariffs and model identifiers change.
