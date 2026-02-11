# Calculator Project

A simple calculator library and REST API.

## Requirements

- Python 3.9+
- FastAPI
- Uvicorn

## Installation

```bash
pip install -r requirements.txt
```

## Project Structure

```
calculator.py   — Core arithmetic functions
api.py          — REST API endpoints
utils.py        — Helper utilities
helpers.py      — Additional helper functions   ← FILE DOES NOT EXIST
config.yaml     — Configuration file            ← FILE DOES NOT EXIST
```

## Usage

```python
from calculator import add, subtract, multiply, divide

result = add(2, 3)       # 5
result = divide(10, 2)   # 5.0
```

## API Endpoints

| Method | Path         | Description              |
| ------ | ------------ | ------------------------ |
| GET    | /health      | Health check             |
| POST   | /calculate   | Perform calculation      |
| GET    | /history     | Get calculation history  |   ← ENDPOINT REMOVED

## Running

```bash
uvicorn api:app --reload --port 8000
```

## Testing

```bash
pytest tests/
```

## License

MIT
