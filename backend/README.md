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

## Admin login

The app starts with a default admin user `cykkk`. The password is stored in the database as a PBKDF2 hash, never as plaintext. Log in through `POST /api/auth/login`, then send protected requests with `Authorization: Bearer <token>`.

## AI chat

The frontend calls `POST /api/advice/chat` and reads the streaming text response. Keep `LLM_API_KEY` on the server; chat requires an active admin login session.
