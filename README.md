# Documentation Freshness Auditor

commands to run the project.

## 1) Setup

```bash
pip install uv
uv sync
```


## 2) Configure `.env`

Create a `.env` file in project root:

```env
API_BASE= https://ollama.com/v1
MODEL_NAME= gemini-3-flash-preview:cloud
OPENAI_API_KEY="api key here"
CREWAI_TRACING_ENABLED=true. 
#MODEL_NAME=rnj-1:8b-cloud

OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_BASE_URL=https://ollama.com/v1
OLLAMA_MODEL=llama3.1:8b
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY="key"  

```

## 3) Run API

```bash
uv run serve
```

## 4) Run Crew (CLI)
`
```bash
uv run run_crew /path/to/project
```

## 5) Run Evals

```bash
uv run eval/eval_run.py -p <project path>
```
