# Fixes

## 1. Query parsing (app/main.py — `clean_json`)
- **Bug:** LLM responses contained markdown fences, surrounding prose, and multiple JSON objects. `json.loads` failed with `Extra data` / invalid JSON.
- **Fix:** Strip Markdown code fences, then scan for the first `{` and parse with `json.JSONDecoder().raw_decode`, which returns the first complete, valid JSON object while ignoring text before/after. Nested and escaped braces are handled by the real JSON parser.
- Verified: `query_db("How many movies are there?")` returns `status=success, type=count, collection=movies`.

## 2. Movie title lookups (prompt rules/examples)
- **Bug:** title questions could be misclassified as `unrelated` or miss the movie.
- **Fix:** Title lookups use an anchored case-insensitive regex (`"$regex": "^<title>$", "$options": "i"`) with `sort:{}` and `limit:1`. Explicit rule added: titles, actors, directors, genres, years, ratings, countries, users, comments, sessions, theaters are always database-related; `unrelated` is reserved for clearly unrelated topics.
- Verified: `Tell me about Larks on a String` → `success`, `collection=movies`, `count=1`.

## 3. Highest/lowest rated queries
- **Bug:** rating queries lacked a proper filter/sort.
- **Fix:** Rating lookups generate `filter: {"imdb.rating": {"$type": "double"}}` with `sort: {"imdb.rating": -1}` (highest) or `1` (lowest) and `limit:1`. Rating words (rating, rated, best, worst, top rated) map to `imdb.rating`.
- Verified: highest → Band of Brothers 9.6; lowest → Justin Bieber 1.6.

## 4. Conversation-memory follow-ups
- **Bug:** `What about 1991?` after `Show me movies from 1990` returned the same 1990 movies. The LLM echoed the previous query as prose, and `clean_json` extracted the echoed (old) query instead of the new one.
- **Fix:**
  - Enabled the provider's JSON mode (`response_format={"type":"json_object"}`) so the LLM returns exactly one clean JSON object.
  - Stored the previous query JSON in memory history so follow-ups resolve deterministically (`What about 1991?` → `{"year": 1991}`).
  - Prompt: follow-ups use only the most recent query, never merge years; added `Which one has the highest rating?` example.
  - Debug prints (`QUESTION`, `HISTORY`, `GENERATED QUERY`) added before execution.
- Verified: `1990 → 1991 → 1992 → {year: 1992} + sort{imdb.rating:-1} + limit 1`.

## 5. Response formatting (app/main.py — `describe`)
- **Bug:** generic `Found N movies.` responses.
- **Fix:** Python-generated text from the actual results:
  - Count: `There are 21,349 movies.`
  - Movie lists: numbered titles (max 10).
  - Title lookup: title, year, genres, directors, runtime, IMDb rating, plot.
  - Highest/lowest: `The highest rated movie is <title> with an IMDb rating of <rating>.`
  - Other collections: identifying fields (email, name, text, theaterId).

## Untouched
PyMongo execution, schema, validation, memory, JSON response format, and the one-LLM-call architecture.
