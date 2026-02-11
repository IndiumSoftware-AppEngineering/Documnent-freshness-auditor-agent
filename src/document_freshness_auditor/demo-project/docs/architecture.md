# Calculator Architecture

## Overview

The calculator project is organized into three modules:

1. **calculator.py** — Core arithmetic operations (add, subtract, multiply, divide)
2. **api.py** — FastAPI REST interface
3. **utils.py** — Formatting and validation helpers
4. **helpers.py** — Extended helper functions  ← MODULE DELETED, STILL REFERENCED

## Data Flow

```
Client Request
    ↓
FastAPI Router (api.py)
    ↓
Validation Layer (utils.validate_number)
    ↓
Calculator Core (calculator.py)
    ↓
Response Formatting (helpers.format_output)  ← FUNCTION DOES NOT EXIST
    ↓
Client Response
```

## API Design

The API exposes three endpoints:

- `GET /health` — Returns service status
- `POST /calculate` — Accepts operation, a, b and returns result
- `GET /history` — Returns past calculations  ← REMOVED IN v2.0

### Authentication

Currently no authentication is required. The `auth.py` middleware
module handles token validation.  ← MODULE DOES NOT EXIST

## Configuration

Settings are loaded from `config.yaml` using the `ConfigLoader` class
in `helpers.py`.  ← BOTH FILE AND CLASS DON'T EXIST

## Future Plans

- Add support for complex number operations
- Implement calculation history with SQLite storage
- Add WebSocket support for real-time calculations
