import os
from flask import Flask, request, render_template, redirect, url_for
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

app = Flask(__name__)

# Initialize SentenceTransformer model
model = SentenceTransformer('microsoft/mpnet-base')

# Connect to MongoDB
uri = CONNECTION_STRING
db_name = DB_NAME
collection_name = COLLECTION_NAME

client = MongoClient(uri, server_api=ServerApi('1'))

# Ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    if 'document' not in request.files:
        return redirect(request.url)
    file = request.files['document']
    if file.filename == '':
        return redirect(request.url)
    if file and file.filename.endswith('.pdf'):
        file_path = os.path.join("documents", file.filename)
        file.save(file_path)

        # Process the document
        elements = partition_pdf(
            file_path, strategy="hi_res", infer_table_structured=True)
        records = convert_to_dict(elements)

        for record in records:
            txt = record['text']
            record['embedding'] = model.encode(txt).tolist()

        # Insert into MongoDB
        client[db_name][collection_name].delete_many({})
        client[db_name][collection_name].insert_many(records)

        return redirect(url_for('index'))


@app.route('/query', methods=['POST'])
def query():
    query_text = request.form['query']
    vector_query = model.encode(query_text).tolist()

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

    results = list(client[db_name][collection_name].aggregate(pipeline))
    context = json.dumps(results)

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a useful assistant. Use the assistant's content to answer the user's query \
        Summarize your answer using the 'texts' and cite the 'page_number' and 'filename' metadata in your reply."},
            {"role": "assistant", "content": context},
            {"role": "user", "content": query_text}
        ]
    )

    answer = response.choices[0].message.content

    return render_template('index.html', query=query_text, answer=answer)


if __name__ == '__main__':
    app.run(debug=True)
