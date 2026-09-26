# Vera AI Challenge - Backend Foundation

This repository contains the backend foundation for the Vera AI Challenge. It implements the required HTTP endpoints and state management, providing a skeleton for the full message generation engine.

## Project Structure

- `bot.py`: The main FastAPI application containing all endpoint routes, data models, and the in-memory context and conversation stores.
- `requirements.txt`: Python package dependencies.
- `test_bot.py`: Test suite verifying endpoint behavior, validation, and state logic.
- `README.md`: This file.

## Setup and Installation

1. Ensure you have Python 3.11+ installed.
2. Install the required dependencies using pip:
   ```bash
   pip install -r requirements.txt
   ```

## Startup

Start the FastAPI application using `uvicorn`:
```bash
uvicorn bot:app --host 0.0.0.0 --port 8080
```
This will start the local server on `http://localhost:8080/`.

## Endpoints

- `GET /v1/healthz`: Liveness probe. Returns server uptime and counts of loaded contexts.
- `GET /v1/metadata`: Returns the bot's identity, team details, and approach.
- `POST /v1/context`: Idempotent endpoint to load or update context payloads (Categories, Merchants, Customers, Triggers). Ensures atomic version updates and rejects older stale versions with a `409 Conflict`.
- `POST /v1/tick`: Receives simulated time and active triggers. (Currently implements temporary behavior: returns `{"actions": []}`).
- `POST /v1/reply`: Receives replies from simulated merchants/customers. (Currently implements temporary behavior: returns a graceful wait action).

## Tests

The project includes a comprehensive test suite using `pytest`.
Run the tests with:
```bash
python -m pytest test_bot.py -v
```

**Tested functionality:**
- Endpoint availability and schema compliance.
- Atomic context updates and correct HTTP 409 handling for stale/duplicate context versions.
- Context validation (invalid scope rejection).
- State persistence of conversations across requests.

## Limitations (Temporary)

- Contexts and conversations are stored purely in memory. They will be wiped if the server restarts.
- The `compose()` function and LLM interactions are not yet implemented.
- `/v1/tick` always returns an empty actions array.
- `/v1/reply` returns a generic `wait` fallback response.
