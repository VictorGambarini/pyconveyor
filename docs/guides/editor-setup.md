# Editor Setup

pyconveyor ships a JSONSchema for the pipeline YAML format. Pointing your editor at it gives you inline autocomplete, field validation, and hover documentation while writing pipelines.

## VS Code

### Automatic setup via `pyconveyor init`

`pyconveyor init` generates `.vscode/settings.json` and `pyconveyor-schema.json` automatically. If you used `init`, you're already set up.

### Manual setup

**Step 1** — Install the [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) by Red Hat.

**Step 2** — Export the schema:

```bash
pyconveyor schema > pyconveyor-schema.json
```

**Step 3** — Add to `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "./pyconveyor-schema.json": "pipeline.yaml"
  }
}
```

To apply the schema to all YAML files matching a pattern:

```json
{
  "yaml.schemas": {
    "./pyconveyor-schema.json": ["pipeline.yaml", "pipelines/*.yaml"]
  }
}
```

---

## JetBrains IDEs (PyCharm, IntelliJ)

**Step 1** — Export the schema:

```bash
pyconveyor schema > pyconveyor-schema.json
```

**Step 2** — Open **Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings**.

**Step 3** — Add a new mapping:
- Schema file: `pyconveyor-schema.json`
- File pattern: `pipeline.yaml` (or `*.pipeline.yaml`)

---

## Neovim (with `nvim-lspconfig`)

Install `yaml-language-server` and configure it to use the schema:

```lua
require('lspconfig').yamlls.setup({
  settings = {
    yaml = {
      schemas = {
        ["./pyconveyor-schema.json"] = "pipeline.yaml",
      },
    },
  },
})
```

---

## Keeping the schema up to date

Re-run `pyconveyor schema > pyconveyor-schema.json` after upgrading pyconveyor to pick up new fields added in the new version. The schema reflects the exact version of pyconveyor installed in your environment.

---

## What the schema covers

The JSONSchema validates:

- Top-level keys (`models`, `parsers`, `steps`)
- All model block fields with their types and defaults
- All step fields with their types, enum values, and defaults
- Step type (`llm`, `transform`, `io`, `validate`, `parallel`, `condition`)
- `on_error` enum values (`raise`, `continue`, `skip_remaining`)
- `retry_on` array items (`schema`, `parse`, `timeout`, `http_error`, `rate_limit`)

It does not validate cross-references (e.g., whether a step's `model:` exists in `models:`). Those checks happen at `PipelineRunner` load time and are reported with line numbers via `pyconveyor validate`.
