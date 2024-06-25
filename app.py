import os
from unstructured.partition.pdf import partition_pdf
from unstructured.staging.base import convert_to_dict
from sentence_transformers import SentenceTransformer
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv
import openai
import json

load_dotenv()
CONNECTION_STRING = os.getenv("MONGODB_CONNECTION_STRING")
DB_NAME = os.getenv("MONGODB_DB_NAME")
COLLECTION_NAME = os.getenv("MONGODB_COLLECTION_NAME")
os.environ["TOKENIZERS_PARALLELISM"] = "false"
openai.api_key = os.getenv("OPENAI_API_KEY")

uri = CONNECTION_STRING
db_name = DB_NAME
collection_name = COLLECTION_NAME

elements = partition_pdf("documents/Document2.pdf",
                         strategy="hi_res",
                         infer_table_structured=True)

records = convert_to_dict(elements)

model = SentenceTransformer('microsoft/mpnet-base')

for record in records:
    txt = record['text']
    record['embedding'] = model.encode(txt).tolist()

# Connect to the server
client = MongoClient(uri, server_api=ServerApi('1'))

# Ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

# delete all first
client[db_name][collection_name].delete_many({})

# insert
client[db_name][collection_name].insert_many(records)

query = "Summarize about the document."

vector_query = model.encode(query).tolist()
# print("The vector query==", vector_query)
# print("\n")

pipeline = [
    {
        "$vectorSearch": {
            "index": "vector_index_new",
            "path": "embedding",
            "queryVector": vector_query,
            "numCandidates": 100,
            "limit": 20
        }
    },
    {
        "$project": {
            "embedding": 0,
            "_id": 0,
            "score": {
                "$meta": "searchScore"
            },
        }
    }
]

print("The pipeline==", pipeline)
print("\n")
print(client[db_name][collection_name].aggregate(pipeline))

results = list(client[db_name][collection_name].aggregate(pipeline))
print("Results====", results)

context = json.dumps(results)

response = openai.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a useful assistant. Use the assistant's content to answer the user's query \
        Summarize your answer using the 'texts' and cite the 'page_number' and 'filename' metadata in your reply."},
        {"role": "assistant", "content": context},
        {"role": "user", "content": query}
    ]
)

print("\n")
print("The response is==", response.choices[0].message.content)
