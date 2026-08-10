from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from .main import query_db
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="text2db")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class QueryRequest(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):

    config = {
        "title": "text2db",
        "subtitle": "Ask a question and get results from the database",
        "placeholder": "e.g., count the number of movies",
        "db_name": os.getenv("MONGO_DB_NAME", "sample_mflix"),
        "llm_model": os.getenv("LLM_MODEL", "local-model"),
        "collections": [
            "movies",
            "users",
            "comments",
            "sessions",
            "theaters"
        ]
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            **config
        }
    )

@app.post("/api/query")
async def api_query(data: QueryRequest):

    if not data.question.strip():
        return {
            "error": "No question provided"
        }

    return query_db(data.question)