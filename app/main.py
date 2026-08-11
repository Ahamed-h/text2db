import json
import os
import re

from dotenv import load_dotenv
from pymongo import MongoClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_classic.memory import ConversationBufferMemory

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "sample_mflix")

if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI not configured")

client = MongoClient(MONGODB_URI)
db = client[MONGODB_DATABASE]

model = ChatOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL, temperature=0)

SCHEMA = {
    "movies": ["_id", "title", "plot", "genres", "cast", "directors", "year", "rated",
               "runtime", "imdb.rating", "imdb.votes", "languages", "countries", "released", "type"],
    "comments": ["_id", "name", "email", "movie_id", "text", "date"],
    "sessions": ["_id", "user_id", "jwt"],
    "users": ["_id", "name", "email", "password"],
    "theaters": ["_id", "theaterId", "location"],
}

schema = json.dumps(SCHEMA, indent=2)
memory = ConversationBufferMemory(memory_key="history", return_messages=False)
# Natural language → MongoDB query (the ONLY LLM call per question)
query_chain = (
    PromptTemplate.from_template(
        """Convert the question into ONE MongoDB query, using conversation history for follow-ups.

Schema (only these collections and fields):
{schema}

Conversation history:
{history}

Question:
{question}

Output ONLY JSON:
- DB question: {{"status":"query","collection":"<c>","operation":"find"|"count","filter":{{}},"sort":{{}},"limit":10}}
- Clearly unrelated: {{"status":"unrelated"}}

Rules:
- Status: ONLY {{"status":"query"}} or {{"status":"unrelated"}}; exactly one JSON object, nothing else.
- NEVER unrelated for movie/film/title/actor/cast/director/genre/rating/rated/year/count/user/comment/session/theater/highest/lowest/best/worst/top rated/show/list/find/tell me about, or any follow-up to a prior DB question. Unrelated only for clearly unrelated topics (weather, politics, general knowledge).
- Collections: movies, users, comments, sessions, theaters. Operations: find or count. Only schema fields. Rating words → imdb.rating; actors → cast; directors → directors.
- Arrays (genres, cast, directors, languages, countries) use {{"$in":["value"]}}.
- Title lookup: naming a specific movie → {{"filter":{{"title":{{"$regex":"^<title>$","$options":"i"}}}},"sort":{{}},"limit":1}}.
- Highest/best/top rated → {{"filter":{{"imdb.rating":{{"$type":"double"}}}},"sort":{{"imdb.rating":-1}},"limit":1}}. Lowest/worst → {{"filter":{{"imdb.rating":{{"$type":"double"}}}},"sort":{{"imdb.rating":1}},"limit":1}}. The {{"$type":"double"}} filter is REQUIRED for rating lookups; never use an empty filter.
- count: empty filter unless needed, no sort/limit. find: limit 10 default. Years: {{"year":<number>}}.
- Fix obvious typos ("moviee"→"movie") before deciding unrelated. Follow-ups: use ONLY the MOST RECENT previous query from history (the last "Query:" line); never merge or combine earlier queries. Generate a NEW query changing only what the current question asks (e.g. "What about 1991?" → replace year with 1991; "Which one has the highest rating?" → keep the most recent filter, add sort {{"imdb.rating":-1}}, limit 1; "What about horror movies?" → change filter to {{"genres":{{"$in":["horror"]}}}}).

Examples:
How many movies are there? → {{"status":"query","collection":"movies","operation":"count","filter":{{}}}}
Show me movies from 1990 → {{"status":"query","collection":"movies","operation":"find","filter":{{"year":1990}},"limit":10}}
What about 1991? → {{"status":"query","collection":"movies","operation":"find","filter":{{"year":1991}},"limit":10}}
Which one has the highest rating? (previous filter year 1992) → {{"status":"query","collection":"movies","operation":"find","filter":{{"year":1992}},"sort":{{"imdb.rating":-1}},"limit":1}}
What is the highest rated movie? → {{"status":"query","collection":"movies","operation":"find","filter":{{"imdb.rating":{{"$type":"double"}}}},"sort":{{"imdb.rating":-1}},"limit":1}}
What is the lowest rated movie? → {{"status":"query","collection":"movies","operation":"find","filter":{{"imdb.rating":{{"$type":"double"}}}},"sort":{{"imdb.rating":1}},"limit":1}}
Tell me about Larks on a String → {{"status":"query","collection":"movies","operation":"find","filter":{{"title":{{"$regex":"^Larks on a String$","$options":"i"}}}},"sort":{{}},"limit":1}}
Who directed Larks on a String? → {{"status":"query","collection":"movies","operation":"find","filter":{{"title":{{"$regex":"^Larks on a String$","$options":"i"}}}},"sort":{{}},"limit":1}}
What is the capital of France? → {{"status":"unrelated"}}
"""
    )
    | model.bind(response_format={"type": "json_object"})
    | StrOutputParser()
)

def error(text, type_, **extra):
    return {"text": text, "json": {"status": "error", "type": type_, **extra}}
def clean_json(content):
    content = re.sub(r"```(?:json)?|```", "", content, flags=re.IGNORECASE).strip()
    for m in re.finditer(r"\{", content):
        try:
            return json.JSONDecoder().raw_decode(content[m.start():])[0]
        except json.JSONDecodeError:
            continue
    raise ValueError("Invalid JSON from LLM")


def validate_query(q):
    if q.get("status") == "unrelated":
        return
    if q.get("status") != "query":
        raise ValueError("Invalid query status")

    collection = q.get("collection")
    operation = q.get("operation")
    filter_ = q.get("filter", {})

    if collection not in SCHEMA:
        raise ValueError("Invalid collection")
    if operation not in {"find", "count"}:
        raise ValueError("Invalid operation")
    if not isinstance(filter_, dict):
        raise ValueError("Invalid filter")

    forbidden = {"$where", "$function", "$accumulator"}

    def check_filter(value):
        if isinstance(value, dict):
            for key, val in value.items():
                if key in forbidden:
                    raise ValueError(f"Forbidden operator: {key}")
                check_filter(val)
        elif isinstance(value, list):
            for item in value:
                check_filter(item)

    check_filter(filter_)


def describe(collection, docs, sort):
    if not docs:
        return f"No matching {collection} found."
    if sort.get("imdb.rating") in (-1, 1):
        return f"The {'highest' if sort['imdb.rating'] == -1 else 'lowest'} rated movie is {docs[0].get('title')} with an IMDb rating of {docs[0].get('imdb', {}).get('rating')}."
    key = {"users": "email", "comments": "name", "sessions": "user_id", "theaters": "theaterId"}.get(collection)
    if collection == "movies" and len(docs) == 1:
        d = docs[0]
        bits = [str(d["year"])] if d.get("year") else []
        if d.get("genres"): bits.append("Genres: " + ", ".join(d["genres"]))
        if d.get("directors"): bits.append("Directed by " + ", ".join(d["directors"]))
        if d.get("runtime"): bits.append(f"Runtime: {d['runtime']} min")
        if d.get("imdb", {}).get("rating"): bits.append(f"IMDb rating: {d['imdb']['rating']}")
        s = f"{d.get('title', '?')} ({'; '.join(bits)})" if bits else str(d.get("title", "?"))
        if d.get("plot"): s += f"\n{d['plot']}"
        return s
    return f"Here are {len(docs)} {collection}:\n" + "\n".join(f"{i}. {d.get('title', '?') if collection == 'movies' else (d.get(key) or d.get('name') or d.get('title') or d.get('text') or '?')}" for i, d in enumerate(docs[:10], 1))


def query_db(question: str):
    history = memory.load_memory_variables({}).get("history", "")

    # ONE LLM call: natural language → MongoDB query
    try:
        content = query_chain.invoke({"question": question, "history": history, "schema": schema})
        query = clean_json(content)
        validate_query(query)
        print("QUESTION:", question); print("HISTORY:", history); print("GENERATED QUERY:", query)
    except Exception as e:
        return error("Failed to generate a valid database query", "query_error", error=str(e))
    # Irrelevant question
    if query.get("status") == "unrelated":
        result = {"text": "This question is not related to the available database.",
                  "json": {"status": "unanswered", "type": "irrelevant_question"}}
        memory.save_context({"input": question}, {"output": result["text"]})
        return result
    collection = query["collection"]
    operation = query["operation"]
    filter_, sort = query.get("filter", {}), query.get("sort", {})

    # Execute MongoDB query
    try:
        if operation == "count":
            count = db[collection].count_documents(filter_)
            result = {
                "text": f"There are {count:,} {collection}.",
                "json": {"status": "success", "type": "count", "collection": collection,
                         "filter": filter_, "result": count, "count": count},
            }
        else:
            limit = query.get("limit", 1 if sort else 10)
            cursor = db[collection].find(filter_, {"_id": 0, "password": 0})
            if sort:
                cursor = cursor.sort(list(sort.items()))
            docs = list(cursor.limit(limit))
            result = {
                "text": describe(collection, docs, sort),
                "json": {"status": "success", "type": "find", "collection": collection,
                         "filter": filter_, "result": docs, "count": len(docs)},
            }
    except Exception as e:
        return error("Database query failed", "database_error", error=str(e))

    memory.save_context({"input": question}, {"output": f"{result['text']}\nQuery: {json.dumps(query)}"})
    return result


if __name__ == "__main__":
    while True:
        question = input("\nAsk a question: ")
        if question.lower() in {"exit", "quit"}:
            break
        print(json.dumps(query_db(question), indent=2, default=str))
