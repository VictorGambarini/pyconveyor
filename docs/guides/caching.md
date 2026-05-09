# Response Caching

pyconveyor includes a file-based response cache for development use. It stores LLM responses on disk so repeated pipeline runs with the same inputs return instantly without API calls.

!!! warning "Development only"
    Never enable caching in production. The cache stores model responses verbatim and will silently serve stale data. A one-time WARNING is logged the first time a cache hit occurs during a run.

---

## Configuration

Enable caching per model in `pipeline.yaml`:

```yaml
models:
  default:
    provider: openai_compat
    base_url: ${OPENAI_BASE_URL}
    api_key:  ${OPENAI_API_KEY}
    model:    gpt-4o-mini
    cache:
      enabled:  true
      dir:      .pyconveyor-cache   # cache directory (default)
      ttl_days: 7                   # expire entries after 7 days (omit for no expiry)
```

---

## Cache key

The cache key is a SHA-256 hash of:

- Provider name
- Model name
- Messages (prompt + any prior conversation turns)
- Sampling parameters (`temperature`, `top_p`, `max_tokens`, `seed`)

Two calls with identical inputs always hit the same cache entry. Changing any sampling parameter invalidates the cache.

---

## CLI flags

```bash
# Use cache (default when enabled in YAML)
pyconveyor run pipeline.yaml --input input.json

# Bypass cache reads but write new entries on success
pyconveyor run pipeline.yaml --input input.json --refresh-cache

# Disable cache entirely for this run
pyconveyor run pipeline.yaml --input input.json --no-cache
```

---

## Python API

```python
runner = PipelineRunner("pipeline.yaml")

# Default: use cache as configured in YAML
rctx = runner.run(input_data)

# Refresh: ignore cached responses, write new ones
rctx = runner.run(input_data, refresh_cache=True)

# Disable: skip cache entirely for this run
rctx = runner.run(input_data, use_cache=False)
```

Cache hit/miss counts are exposed in `RunSummary`:

```python
summary = rctx.summary()
print(f"Cache hits: {summary.cache_hits}, misses: {summary.cache_misses}")
```

---

## Cache directory

The default cache directory is `.pyconveyor-cache/` relative to the working directory. Add it to `.gitignore`:

```
.pyconveyor-cache/
```

`pyconveyor init` adds this entry automatically.

---

## `ResponseCache` standalone API

```python
from pyconveyor.cache import ResponseCache

cache = ResponseCache(directory=".pyconveyor-cache", ttl_days=7)

# Check for a cached response
response = cache.get(
    provider="openai_compat",
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}],
    sampling={"temperature": 0.1},
)

if response is None:
    # Cache miss — call the API
    response = call_api(...)
    cache.set(provider, model, messages, sampling, response)
```
