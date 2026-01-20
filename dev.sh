#!/bin/bash

# Run the API server
# For background workers, run in separate terminals:
#   uv run rq worker high default --url redis://localhost:6379
#   uv run rqscheduler --url redis://localhost:6379

uv run uvicorn solana_agent_api.main:app --reload --port=8080 --timeout-graceful-shutdown 30 --workers 1
