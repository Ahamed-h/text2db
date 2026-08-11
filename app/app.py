from pathlib import Path
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .main import query_db

load_dotenv()

app = FastAPI(title="text2sql")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class QueryRequest(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    config = {
        "title": "text2sql",
        "subtitle": "Conversational database queries powered by AI",
        "placeholder": "Ask about movies, users, comments, sessions...",
        "db_name": os.getenv("MONGODB_DATABASE", "sample_mflix"),
        "llm_model": os.getenv(
            "LLM_MODEL",
            "llama-3.1-8b-instant"
        ),
    }

    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request, **config}
    )


@app.post("/api/query")
async def api_query(data: QueryRequest):
    if not data.question.strip():
        return {
            "text": "Please provide a question.",
            "json": {
                "status": "error",
                "type": "empty_question"
            }
        }

    return query_db(data.question)