#!/bin/bash
echo "[START] Railway start.sh executing at $(date)" >&2
echo "[START] PORT=$PORT" >&2
echo "[START] RAILWAY_ENVIRONMENT=$RAILWAY_ENVIRONMENT" >&2
echo "[START] Python version: $(python --version 2>&1)" >&2
echo "[START] Working directory: $(pwd)" >&2
echo "[START] Starting Streamlit..." >&2

exec streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 2>&1
