# ScienceUnbound

Turn a finished study that never got published into a **checked, citable report**: every number verified against its table, identifiers never leaving your control, the plan locked before the data is read.

## Credit

The idea of an agent-friendly platform that turns unpublished projects into checked, citable research reports **originates with [Yamil Ricardo Velez](https://github.com/yrvelez/filedrawer)** (Filedrawer.org), who built the first version after Robb Willer raised automated public research reports as a response to publication bias.
ScienceUnbound is an independent re-implementation for use with your own research. It contains no code from Filedrawer and is not affiliated with or endorsed by its author.

## Use

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Open **New study**, load the synthetic demo or your own CSV / Stata / Excel file, and follow six steps: Data, Privacy, Plan, Analyze, Report, Publish.
The CLI does the same without the app: `scienceunbound audit|run|lock|reproduce|check|meta|demo`.

### Host it (Streamlit Community Cloud)

1. Deploy this repository with `streamlit_app.py` as the main file.
2. In *Settings → Secrets* add `SU_MODE = "hosted"`, `GITHUB_TOKEN = "…"` (fine-grained, *Contents: write*, this repository only) and optionally `SU_GITHUB_REPO = "owner/name"`.
3. Published studies are committed to `studies/<slug>/`. The app redeploys and the Library lists them.

Hosted mode processes uploads in server memory. For raw data with identifiers, run locally.

## Use a language model (optional, never required)

Everything works without one. A model only drafts the plan from your pasted text and writes the summary prose. It sees column names, your plan text and result ids and verdicts, never a data row, and it never writes a number (placeholders are filled from the tables; any literal digit is rejected and retried).

**Free and private: a local model** (needs ScienceUnbound running on your own computer).
1. Install [Ollama](https://ollama.com) (or LM Studio).
2. `ollama pull qwen3:8b` (about 6 GB of memory; an 8B-class instruct model is enough for this task. Larger models write slightly better prose.)
3. `scienceunbound llm-check --provider ollama` tests the whole path on the demo study.
4. In the app: *AI settings → Ollama → Test the connection*.

Paid options: `anthropic` or `openai_compatible` (OpenRouter and others). Put the key in the secret `SU_LLM_API_KEY` instead of typing it. A ChatGPT or Claude chat subscription does not include API access; there is no sanctioned way to use one as an app backend.

## What it checks

| Step | Guarantee | How it is tested |
|---|---|---|
| Privacy | every cell scanned for identifiers, free text and timestamps; re-identification risk (k-anonymity) measured and reduced; all files re-scanned before commit | planted identifiers in blank-at-the-top columns; clean-survey false-positive check |
| Statistics | effect sizes with CIs, Holm / Benjamini-Hochberg, equivalence tests, minimum detectable effect, specification curves | agreement with scipy / statsmodels to 1e-9; CI coverage and type-I error in simulation with planted truth |
| Report | an independent script checks every number against the tables, binds result lines to their own rows, and detects omitted estimates | injected-defect tests; measured detection of fabricated numbers: 91–98 % depending on where they are inserted |
| Plan | structured plan, SHA-256 lock, field-by-field deviations, timing against data collection | tamper and deviation tests |
| Reproduce | tolerance-based re-run, hash manifest | forged-results tests |

### Limits

Verification shows every number comes from the tables, not that the tables suit your design. A lock time made in the app is self-asserted until it is committed to GitHub. Survey weights, multilevel and non-linear models are not supported. A pooled meta-analysis of studies that authors chose to publish can still be selected.

## Tests

```bash
pip install pytest && pytest -q
```

## Licence

Code: MIT. Reports and data you publish: CC BY 4.0 unless you change it in `study.json`.
