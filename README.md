# text2db

Ask questions in natural language and get answers from a MongoDB database.

text2db converts natural-language questions into MongoDB queries, runs them
against MongoDB, and returns the results as both a natural-language answer
and the raw JSON, through a FastAPI web UI.

## How it works

```
Natural language question
→ LLM generates MongoDB query
→ MongoDB executes query
→ JSON result
→ LLM generates natural-language answer
→ FastAPI returns response
→ Frontend displays answer and JSON
```

## Features

- Web UI (Jinja2 + HTML) to ask questions and view results
- An OpenAI-compatible LLM converts questions into MongoDB queries (count/find)
- LLM answer generation from the query results
- Query validation against a fixed schema of collections and fields
- REST API endpoint: `POST /api/query`

## Technologies

- FastAPI
- MongoDB (PyMongo)
- OpenAI-compatible LLM (OpenAI SDK)
- Jinja2
- Python

## Project structure

```
app/
  app.py        # FastAPI app and routes
  main.py       # LLM query generation and query execution
  mongodb.py    # MongoDB client and database handle
  templates/
    index.html  # Frontend page
api/
  index.py      # Vercel serverless entry point
.env.example    # Example environment variables
requirements.txt
```

## Local setup

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a `.env` file from `.env.example` and fill in real values.

3. Point MongoDB at a database matching the schema in `app/main.py`
   (collections: `movies`, `users`, `comments`, `sessions`, `theaters`).

4. Provide an OpenAI-compatible LLM endpoint.

## Required environment variables

| Variable        | Description                                          |
|-----------------|------------------------------------------------------|
| `MONGO_URI`     | MongoDB connection string                            |
| `MONGO_DB_NAME` | Database name (default `sample_mflix`)               |
| `LLM_BASE_URL`  | OpenAI-compatible API base URL                       |
| `LLM_API_KEY`   | API key for the LLM provider                         |
| `LLM_MODEL`     | Model name to use                                    |

Note: the application reads `MONGO_URI` (see `app/mongodb.py`).

## How to run locally

```bash
uvicorn app.app:app --reload --port 5000
```

Open http://localhost:5000 in a browser.

## How to test the API

```bash
curl -X POST http://localhost:5000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "count the number of movies"}'
```

## How to deploy to Vercel

1. Push the project to a GitHub repository.
2. Import the repository in Vercel.
3. Set the environment variables (`MONGO_URI`, `MONGO_DB_NAME`,
   `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) in the Vercel project settings.
4. Deploy. The `api/index.py` file exposes the FastAPI app as a serverless
   function.

## Example questions

- count the number of movies
- movies from 1990
- how many users are there
- tell me about Larks
- find theaters in a city

For sample_mflix-style data: `movies`, `users`, `comments`, `sessions`,
`theaters`.
