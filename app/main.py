import json, os, re
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import pyodbc
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_classic.memory import ConversationBufferMemory

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
MONGODB_ODBC_CONNECTION_STRING = os.getenv("MONGODB_ODBC_CONNECTION_STRING")
model = ChatOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL, temperature=0)

SCHEMA = {
    "movies": {
        "_id": "objectId",
        "title": "string",
        "plot": "string",
        "genres": "array[string]",
        "cast": "array[string]",
        "directors": "array[string]",
        "year": "integer",
        "rated": "string",
        "runtime": "integer",
        "imdb.rating": "number",
        "imdb.votes": "integer",
        "languages": "array[string]",
        "countries": "array[string]",
        "released": "date",
        "type": "string"
    },
    "comments": {
        "_id": "objectId",
        "name": "string",
        "email": "string",
        "movie_id": "objectId",
        "text": "string",
        "date": "timestamp"
    },
    "sessions": {
        "_id": "objectId",
        "user_id": "string",
        "jwt": "string"
    },
    "users": {
        "_id": "objectId",
        "name": "string",
        "email": "string",
        "password": "string"
    }
}

memory = ConversationBufferMemory(memory_key="history", return_messages=False)

class SQLQuery(BaseModel):
    query: str = Field(description="A read-only SQL SELECT query")

sql_parser = PydanticOutputParser(pydantic_object=SQLQuery)

rewrite_chain = (
    PromptTemplate.from_template(
        """You are a database question rewriting assistant.
Rewrite the user's question for SQL conversion:
- Do NOT answer or create SQL
- Do NOT invent information
- Keep original meaning
- Use table/field names when possible
- Resolve references from history

Schema: {schema}
History: {history}
Question: {question}

Return ONLY the rewritten question."""
    )
    | model
    | StrOutputParser()
)

sql_chain = (
    PromptTemplate.from_template(
        """You are an SQL query generator for MongoDB SQL Interface.

Convert the question into a READ-ONLY SQL query.

Tables & fields:
{schema}

Rules:
1. ONLY SELECT statements
2. Forbidden: INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE
3. "count/how many" = COUNT(*)
4. Use WHERE for filtering
5. Use ORDER BY for sorting
6. Use LIMIT 10 for normal requests
7. Use ARRAY_CONTAINS for array fields (cast, genres, directors, languages, countries)
8. Use LIKE '%text%' for text search
9. Never invent tables or fields
10. Return ONLY the SQL query

Examples:
Q: How many movies are there?
A: SELECT COUNT(*) AS movie_count FROM movies;

Q: Movies with Tom Hanks?
A: SELECT * FROM movies WHERE ARRAY_CONTAINS(cast, 'Tom Hanks') LIMIT 10;

Q: Horror movies from 2020?
A: SELECT * FROM movies WHERE ARRAY_CONTAINS(genres, 'Horror') AND year = 2020 LIMIT 10;

{format_instructions}

Question: {rewritten_question}"""
    ).partial(format_instructions=sql_parser.get_format_instructions())
    | model
    | sql_parser
)

answer_chain = (
    PromptTemplate.from_template(
        """Answer the user's question using ONLY the database result.

Original: {question}
Rewritten: {rewritten_question}
SQL: {sql_query}
Result: {database_data}

Rules:
- No invented information
- Use only the result
- If empty, say no data found
- Be concise
- No implementation details"""
    )
    | model
    | StrOutputParser()
)

def get_sql_connection():
    if not MONGODB_ODBC_CONNECTION_STRING:
        raise RuntimeError("MONGODB_ODBC_CONNECTION_STRING not configured")
    return pyodbc.connect(MONGODB_ODBC_CONNECTION_STRING)

def validate_sql(query: str) -> str:
    query = query.strip()
    query = re.sub(r"```(?:sql)?", "", query, flags=re.IGNORECASE).replace("```", "").strip()
    query = query.rstrip(";").strip()
    
    if not re.match(r"^SELECT\b", query, flags=re.IGNORECASE):
        raise ValueError("Only SELECT queries allowed")
    
    for keyword in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]:
        if re.search(rf"\b{keyword}\b", query, flags=re.IGNORECASE):
            raise ValueError(f"Forbidden operation: {keyword}")
    
    return query

def execute_sql(query: str):
    connection, cursor = None, None
    try:
        connection = get_sql_connection()
        cursor = connection.cursor()
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def query_db(question: str):
    history = memory.load_memory_variables({}).get("history", "")
    
    try:
        rewritten = rewrite_chain.invoke({
            "question": question,
            "history": history,
            "schema": json.dumps(SCHEMA, indent=2)
        }).strip()
    except Exception as e:
        return {"text": "Failed to rewrite question", "json": {"status": "error", "type": "rewrite_error", "error": str(e)}}
    
    try:
        sql_query = sql_chain.invoke({
            "rewritten_question": rewritten,
            "schema": json.dumps(SCHEMA, indent=2)
        }).query
    except Exception as e:
        return {"text": "Failed to generate SQL", "json": {"status": "error", "type": "sql_generation_error", "error": str(e)}}
    
    try:
        sql_query = validate_sql(sql_query)
    except Exception as e:
        return {"text": "SQL query not allowed", "json": {"status": "error", "type": "invalid_sql", "sql_query": sql_query, "error": str(e)}}
    
    try:
        result = execute_sql(sql_query)
    except Exception as e:
        return {"text": "Database query failed", "json": {"status": "error", "type": "database_error", "sql_query": sql_query, "error": str(e)}}
    
    try:
        answer = answer_chain.invoke({
            "question": question,
            "rewritten_question": rewritten,
            "sql_query": sql_query,
            "database_data": json.dumps(result, indent=2, default=str)
        }).strip()
    except Exception:
        answer = "No matching data found" if not result else f"Found {len(result)} result(s)"
    
    memory.save_context({"input": question}, {"output": answer})
    
    return {
        "text": answer,
        "json": {
            "status": "success",
            "type": "sql",
            "original_question": question,
            "rewritten_question": rewritten,
            "sql_query": sql_query,
            "result": result,
            "count": len(result)
        }
    }

if __name__ == "__main__":
    while True:
        question = input("\nAsk a question: ")
        if question.lower() in {"exit", "quit"}:
            break
        print(json.dumps(query_db(question), indent=2, default=str))