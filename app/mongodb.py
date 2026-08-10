import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI","mongodb://localhost:27017")
client = MongoClient(MONGO_URI)

MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "sample_mflix")
db = client[MONGO_DB_NAME]
