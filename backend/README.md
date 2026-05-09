# Backend

FastAPI service for fund NAV updates, portfolio calculation, and AI advice.

## Local run

```bash
cd backend
conda env create -f environment.yml
conda activate my-financing
uvicorn app.main:app --reload
```

API docs: <http://localhost:8000/docs>

## AI chat

The frontend calls `POST /api/advice/chat` and reads the streaming text response. Keep `LLM_API_KEY` on the server and pass `X-Admin-Token` from your personal frontend session.
