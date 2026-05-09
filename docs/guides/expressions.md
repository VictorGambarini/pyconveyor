# Expression Language

pyconveyor uses `{{ expr }}` expressions in step `inputs`, `vars`, and `condition` fields to reference context values and prior step results.

## Where expressions are used

```yaml
steps:
  - name: reconcile
    type: transform
    fn: steps:reconcile
    inputs:
      primary:  "{{ steps.extract.primary }}"
      reviewer: "{{ steps.extract.reviewer }}"
    condition: "{{ steps.extract.primary is not none }}"
```

Any YAML string wrapped in `{{ }}` is an expression. Strings without `{{ }}` are treated as literals.

## Available roots

| Root | Description |
|---|---|
| `ctx` | The input dict passed to `runner.run()` — access as `ctx.key` or `ctx["key"]` |
| `steps` | Completed step results — access as `steps.step_name.value` |

For `parallel` steps, child results are nested: `steps.extract.primary` accesses the `primary` child of a parallel step named `extract`.

## Allowed syntax

pyconveyor evaluates expressions through a **strict AST whitelist**. Only these constructs are permitted:

| Construct | Example |
|---|---|
| Attribute access | `ctx.document`, `steps.extract.value` |
| Item lookup | `ctx["key"]` |
| Boolean operators | `x and y`, `x or y`, `not x` |
| Comparison operators | `==`, `!=`, `is`, `is not`, `in`, `not in` |
| Ternary expressions | `x if condition else y` |
| String and numeric literals | `"text"`, `42`, `3.14` |
| Constants | `None`, `True`, `False` |
| Whitelisted functions | `first_non_none(...)`, `active_models(...)`, `len(...)` |

Any expression containing a node outside this set raises `ExpressionSecurityError` at **pipeline load time** — before any run begins — with the file name, YAML key path, and the offending expression in the message.

## Helper functions

### `first_non_none`

Returns the first argument that is not `None`. Useful when a step's result is optional:

```yaml
inputs:
  result: "{{ first_non_none(steps.reconcile.value, steps.extract.primary) }}"
```

### `len`

Returns the length of a sequence:

```yaml
condition: "{{ len(ctx.documents) > 0 }}"
```

### `active_models`

Returns the set of model names that are configured and `required: false` models that resolved successfully. Rarely needed in step inputs; more useful in condition branches.

## Security model

The whitelist is the whole security model. No `eval()` is involved.

Expressions are parsed with Python's `ast` module and the resulting AST is walked node-by-node. Any node type not on the whitelist causes an immediate rejection at load time. This makes the security boundary:

- **Explicit** — the whitelist is a short list in `expr.py`
- **Auditable** — you can read it in a minute
- **Fail-closed** — unknown constructs are rejected, not silently permitted

This matters if pipeline YAML ever comes from a partially-trusted source (user-uploaded configs, generated pipelines). The runner will reject malicious expressions before executing them.

## Error messages

When an expression fails validation, the error includes:

```
pipeline.yaml:34  steps[2].inputs.primary
  Expression error: 'step' is not a valid root.
  Did you mean: 'steps'?
```

When an expression references a step that doesn't exist:

```
pipeline.yaml:41  steps[3].inputs.result
  Reference error: step 'extact' is not defined.
  Did you mean: 'extract'?
  Defined steps: extract, review, reconcile
```

"Did you mean?" suggestions use string-distance scoring against the set of valid alternatives.

## Null safety

`ctx` uses a null-safe proxy. Accessing a key that doesn't exist returns `None` rather than raising `AttributeError`:

```yaml
condition: "{{ ctx.optional_field is not none }}"
```

This means you can safely reference optional input fields in conditions without wrapping them in a try/except in a transform step first.

## Expressions are not Jinja2

Prompt templates (`.j2` files) use full Jinja2 syntax. Expressions in YAML field values (`inputs:`, `condition:`, etc.) use the restricted AST-whitelisted syntax described here. They look similar but are evaluated differently.

Do not use Jinja2 filters (`| lower`, `| default(...)`) in YAML expressions — they are not supported and will raise `ExpressionSecurityError` at load time.
