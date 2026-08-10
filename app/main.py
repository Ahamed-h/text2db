import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI
from .mongodb import db

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "local-model")

llm = OpenAI(
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY
)

SCHEMA = {
    "movies": {
        "title": "string",
        "plot": "string",
        "genres": "array[string]",
        "cast": "array[string]",
        "year": "integer",
        "rated": "string",
        "imdb.rating": "number"
    },
    "users": {
        "name": "string",
        "email": "string"
    },
    "comments": {
        "name": "string",
        "email": "string",
        "text": "string",
        "date": "date"
    },
    "sessions": {
        "user_id": "string"
    },
    "theaters": {
        "theaterId": "integer",
        "location.address.city": "string"
    }
}


def query_db(question):

    prompt = f"""Return ONLY a valid JSON object.

Convert the user's natural-language question into a MongoDB query.

Available collections and fields:
{json.dumps(SCHEMA, indent=2)}

Allowed operations:
count, find

Rules:
- Understand synonyms and different wording.
- Do not reject a database-related question because of its wording.
- Never invent collections or fields.
- If the exact field is unclear, use important keywords to search the
  most relevant available text field.
- Use case-insensitive regex for text searches.
- "how many", "count", "number of" → count.
- Other information requests → find.
- A query returning zero documents is still a valid answer.
- Only consider a question irrelevant if it has no connection to the database.
- Return ONLY JSON.
- Use double quotes.
- Never use single quotes or markdown.

Examples:

Q: count movies
A: {{"collection":"movies","operation":"count","filter":{{}}}}

Q: movies from 1990
A: {{"collection":"movies","operation":"find","filter":{{"year":1990}}}}

Q: runtime of Larks on a String
A: {{"collection":"movies","operation":"find","filter":{{"title":{{"$regex":"Larks on a String","$options":"i"}}}}}}

Q: tell me about Larks
A: {{"collection":"movies","operation":"find","filter":{{"title":{{"$regex":"Larks","$options":"i"}}}}}}

Q: {question}
A:"""

    try:
        resp = llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Return ONLY valid JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0,
            max_tokens=300
        )

        content = resp.choices[0].message.content.strip()

    except Exception as e:
        return {
            "text": "LLM request failed.",
            "json": {
                "status": "error",
                "error": str(e)
            }
        }

    content = re.sub(
        r"```(?:json)?\s*|\s*```",
        "",
        content,
        flags=re.IGNORECASE
    ).strip()

    try:
        q = json.loads(content)

    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)

        if not match:
            return {
                "text": "Could not understand the query.",
                "json": {
                    "status": "error",
                    "type": "invalid_json"
                }
            }

        try:
            q = json.loads(match.group())
        except json.JSONDecodeError:
            return {
                "text": "Could not understand the query.",
                "json": {
                    "status": "error",
                    "type": "invalid_json"
                }
            }

    collection_name = q.get("collection")
    operation = q.get("operation")
    filt = q.get("filter", {})

    if collection_name not in SCHEMA:
        return {
            "text": "Invalid collection.",
            "json": {
                "status": "error",
                "type": "invalid_collection"
            }
        }

    if operation not in {"count", "find"}:
        return {
            "text": "Invalid operation.",
            "json": {
                "status": "error",
                "type": "invalid_operation"
            }
        }

    collection = db[collection_name]

    if operation == "count":

        count = collection.count_documents(filt)

        return {
            "text": f"There are {count} {collection_name} matching your question.",
            "json": {
                "status": "success",
                "type": "count",
                "result": count,
                "collection": collection_name,
                "filter": filt
            }
        }

    docs = list(
        collection.find(
            filt,
            {
                "_id": 0,
                "password": 0
            }
        ).limit(10)
    )

    answer_prompt = f"""Answer the user's question using ONLY this database JSON.

Question:
{question}

Database JSON:
{json.dumps(docs, default=str, indent=2)}

Do not invent information.
If the data does not contain the answer, say that it is not available.
Keep the answer concise.
"""

    try:
        answer_resp = llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Answer using only the provided database data."
                },
                {
                    "role": "user",
                    "content": answer_prompt
                }
            ],
            temperature=0,
            max_tokens=300
        )

        answer = answer_resp.choices[0].message.content.strip()

    except Exception:
        answer = (
            f"No {collection_name} matched your question."
            if not docs
            else f"Found {len(docs)} {collection_name}."
        )

    return {
        "text": answer,
        "json": {
            "status": "success",
            "type": "find",
            "result": docs,
            "count": len(docs),
            "collection": collection_name,
            "filter": filt
        }
    }


if __name__ == "__main__":
    question = input("Ask a question: ")
    result = query_db(question)
    print(json.dumps(result, indent=2, default=str))