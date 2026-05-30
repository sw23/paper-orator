# Paper Orator

Turn PDF papers into narrated audio podcasts posted to an RSS feed. Reads the source word-for-word, with AI-summarized figures and tables and AI text-to-speech.

## How It Works

Paper Orator processes academic PDFs through a four-stage pipeline:

1. **Extract** — Structured text, tables, and figures are extracted from the PDF using OCR
2. **Clean** — An LLM cleans OCR artifacts, merges broken lines, and describes figures/tables for audio
3. **Speak** — Text-to-speech converts the cleaned text into a natural-sounding MP3
4. **Publish** — The MP3 is added to an RSS feed and optionally uploaded to cloud storage

Each stage saves intermediate files, so you can re-run later stages without repeating earlier ones.

## PrerequisitesP

You need Azure resources for four services. Create them in the [Azure Portal](https://portal.azure.com):

| Service | What it does | Azure resource |
|---|---|---|
| OCR | Extracts text/tables/figures from PDFs | [Document Intelligence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/) |
| LLM | Cleans and prepares text for speech | [Azure OpenAI](https://learn.microsoft.com/en-us/azure/ai-services/openai/) (deploy a model with vision, e.g. `gpt-4.1-mini`) |
| TTS | Converts text to spoken audio | [Speech Service](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/) |
| Storage | Hosts the MP3 and RSS files | [Blob Storage](https://learn.microsoft.com/en-us/azure/storage/blobs/) |

> **Note:** Storage is only needed if you use `--upload`. You can generate audio locally without it.

## Installation

```bash
git clone https://github.com/sw23/paper-orator.git
cd paper-orator
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Create a config file

```bash
paper-orator init
```

This creates `paper_orator.yaml` in your current directory. Edit it with your RSS feed settings:

```yaml
feed:
  title: "My Research Audio Feed"
  description: "Audio versions of research papers"
  link: "https://mysite.com/feed/feed.xml"
  base_url: "https://mysite.com/feed/"
```

### 2. Set environment variables

Export your Azure credentials:

```bash
export AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="https://your-resource.cognitiveservices.azure.com/"
export AZURE_DOCUMENT_INTELLIGENCE_KEY="your-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_KEY="your-key"
export AZURE_OPENAI_DEPLOYMENT="gpt-4.1-mini"
export AZURE_SPEECH_KEY="your-key"
export AZURE_SPEECH_REGION="eastus"

# Only needed for --upload:
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;..."
export AZURE_STORAGE_CONTAINER_NAME="your-container"
```

> **Tip:** Put these in a shell script (e.g. `azure_keys.sh`) and source it: `source azure_keys.sh`

### 3. Process a paper

```bash
paper-orator process paper.pdf --name "Attention-Is-All-You-Need"
```

Output files are saved to `./output/Attention-Is-All-You-Need/`:

```
output/Attention-Is-All-You-Need/
├── raw_text.txt                    # Extracted text from PDF
├── cleaned_text.txt                # LLM-cleaned text ready for TTS
├── Attention-Is-All-You-Need.mp3   # Final audio
├── figure_0.png ... figure_N.png   # Extracted figures
├── table_0.txt ... table_N.txt     # Extracted tables
└── batch_results.zip               # TTS batch output archive
```

### 4. Publish to RSS

```bash
paper-orator process paper.pdf \
  --name "Attention-Is-All-You-Need" \
  --web-url "https://arxiv.org/abs/1706.03762" \
  --update-rss \
  --upload
```

This updates `output/feed.xml` and uploads both the MP3 and feed to Azure Blob Storage.

## CLI Reference

### `paper-orator init`

Create a starter config file.

```
paper-orator init [-o OUTPUT_PATH]
```

| Flag | Description |
|---|---|
| `-o`, `--output` | Output path (default: `paper_orator.yaml`) |

### `paper-orator process`

Process a PDF into narrated audio.

```
paper-orator process PDF_PATH [options]
```

| Flag | Description |
|---|---|
| `-n`, `--name` | Paper name for output directory and filenames. Defaults to the PDF filename. |
| `-c`, `--config` | Config file path (default: `paper_orator.yaml`) |
| `-o`, `--output-dir` | Base output directory (default: `./output`) |
| `--web-url` | URL to the original paper (used as `<link>` in RSS) |
| `--update-rss` | Add/update this paper in the RSS feed |
| `--upload` | Upload MP3 and RSS feed to remote storage |
| `--force` | Overwrite existing output files without prompting |
| `--interactive` | Prompt before overwriting existing output files |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` (default: `INFO`) |

## Config File Reference

The config file (`paper_orator.yaml`) uses YAML format. Environment variables can be referenced with `${VAR_NAME}` syntax.

```yaml
# RSS feed metadata
feed:
  title: "My Research Audio Feed"       # Feed title shown in podcast apps
  description: "Audio versions of ..."  # Feed description
  link: "https://example.com/feed.xml"  # URL to the feed itself
  base_url: "https://example.com/feed/" # Base URL for MP3 file links
  language: "en-us"                     # Feed language code

# Text-to-speech settings
tts:
  voice: "en-US-JennyNeural"   # Azure TTS voice name
  use_batch: true              # true = batch API (long audio), false = SDK (~10 min limit)

# Which backend to use for each pipeline stage
providers:
  ocr: azure
  llm: azure
  tts: azure
  storage: azure

# Azure-specific credentials (referenced via environment variables)
azure:
  document_intelligence:
    endpoint: "${AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT}"
    key: "${AZURE_DOCUMENT_INTELLIGENCE_KEY}"
  openai:
    endpoint: "${AZURE_OPENAI_ENDPOINT}"
    key: "${AZURE_OPENAI_KEY}"
    deployment: "${AZURE_OPENAI_DEPLOYMENT}"
  speech:
    key: "${AZURE_SPEECH_KEY}"
    region: "${AZURE_SPEECH_REGION}"
  storage:
    connection_string: "${AZURE_STORAGE_CONNECTION_STRING}"
    container_name: "${AZURE_STORAGE_CONTAINER_NAME}"
```

See [paper_orator.example.yaml](paper_orator.example.yaml) for a complete template.

## Architecture

Paper Orator uses a pluggable provider architecture. Each pipeline stage is backed by an abstract interface:

| Stage | Interface | Built-in Provider |
|---|---|---|
| Extract | `DocumentExtractor` | `AzureDocumentExtractor` (Document Intelligence) |
| Clean | `TextCleaner` | `AzureTextCleaner` (Azure OpenAI) |
| Speak | `SpeechSynthesizer` | `AzureSpeechSynthesizer` (Cognitive Services) |
| Upload | `StorageUploader` | `AzureBlobUploader` (Blob Storage) |

### Adding a Custom Provider

1. Subclass the appropriate base class from `paper_orator.providers.base`
2. Register it before running the pipeline:

```python
from paper_orator.providers import register_provider
from my_module import MyCustomExtractor

register_provider("ocr", "custom", MyCustomExtractor)
```

3. Set `providers.ocr: custom` in your config file and add a corresponding `custom:` config section.

## Contributing

Contributions are welcome! Some ideas:

- Additional provider backends (AWS, GCP, local/open-source models)
- Unit and integration tests
- Voice selection and SSML customization
- Chapter markers / table of contents in audio

## License

[MIT](LICENSE)
