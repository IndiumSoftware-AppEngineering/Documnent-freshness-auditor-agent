# Software Requirements Specification (SRS)
## Calculator Project — v1.0

| Field       | Value                     |
| ----------- | ------------------------- |
| Project     | Calculator Library & API  |
| Version     | 1.0                       |
| Last Updated| 2025-03-15                |
| Author      | Team Alpha                |

---

## 1. Functional Requirements

### 1.1 Core Arithmetic

| Req ID | Description                                              | Priority |
| ------ | -------------------------------------------------------- | -------- |
| FR-001 | The `add` function shall accept two numbers and return their sum          | High     |
| FR-002 | The `subtract` function shall accept two numbers and return their diff   | High     |
| FR-003 | The `multiply` function shall accept two numbers and return the product  | High     |
| FR-004 | The `divide` function shall raise `ValueError` on division by zero       | High     |
| FR-005 | The `square_root` function shall compute the square root of a number     | Medium   |
| FR-006 | The `modulo` function shall return the remainder of a / b                | Medium   |

> **Note:** FR-005 and FR-006 reference functions (`square_root`, `modulo`)
> that were planned but **never implemented**.

### 1.2 Advanced Operations

| Req ID | Description                                              | Priority |
| ------ | -------------------------------------------------------- | -------- |
| FR-007 | The `power` function shall compute base raised to exponent               | Medium   |
| FR-008 | The `factorial` function shall compute n! recursively                    | Low      |
| FR-009 | The `fibonacci` function shall return nth Fibonacci number               | Low      |
| FR-010 | The `logarithm` function shall compute log base b of a value            | Low      |

> **Note:** FR-010 references `logarithm` which does **not exist** in the codebase.

### 1.3 REST API

| Req ID | Description                                              | Priority |
| ------ | -------------------------------------------------------- | -------- |
| FR-011 | `POST /calculate` shall accept operation, a, b and return result         | High     |
| FR-012 | `GET /health` shall return service health status                         | High     |
| FR-013 | `GET /history` shall return past calculation results                     | Medium   |
| FR-014 | `POST /power` shall compute exponentiation via API                       | Medium   |
| FR-015 | `POST /batch` shall accept an array of calculations                      | Low      |

> **Note:** FR-013 references the `/history` endpoint which was **removed in v2.0**.

### 1.4 Utilities

| Req ID | Description                                              | Priority |
| ------ | -------------------------------------------------------- | -------- |
| FR-016 | `format_result` shall format numbers to given precision                  | Medium   |
| FR-017 | `validate_number` shall check if input is a valid number                 | Medium   |
| FR-018 | `ConfigLoader` class shall load configuration from `config.yaml`         | Low      |

> **Note:** FR-018 references `ConfigLoader` and `config.yaml` which
> **do not exist** — they were removed during refactoring.

---

## 2. Non-Functional Requirements

| Req ID  | Description                                              | Priority |
| ------- | -------------------------------------------------------- | -------- |
| NFR-001 | All functions shall complete within 100ms for inputs < 1000              | High     |
| NFR-002 | The API shall handle 50 concurrent requests                              | Medium   |
| NFR-003 | The `auth.py` middleware shall validate JWT tokens                       | High     |

> **Note:** NFR-003 references `auth.py` which **does not exist** in the project.

---

## 3. Architecture

The project consists of the following modules:

- **`calculator.py`** — Core arithmetic operations
- **`api.py`** — FastAPI REST interface
- **`utils.py`** — Formatting and validation helpers
- **`helpers.py`** — Extended helper functions ← **STALE: module was deleted**
- **`auth.py`** — Authentication middleware ← **STALE: never created**

Data flows from the client through `api.py`, which calls `validate_number`
from `utils.py`, then invokes the appropriate function from `calculator.py`,
and finally formats the output using `helpers.format_output`.

> **Note:** References to `helpers.py`, `helpers.format_output`, and `auth.py`
> are all stale — these were planned but never implemented or were deleted.

---

## 4. Acceptance Criteria

- [ ] All FR-001 through FR-018 are implemented and tested
- [ ] API matches OpenAPI spec (openapi.yaml)
- [ ] All modules listed in §3 exist in the repository
- [ ] Test coverage ≥ 80%
