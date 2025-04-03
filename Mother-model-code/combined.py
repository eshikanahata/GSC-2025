from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio
from threading import Thread
import csv
import io
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import subprocess
from confluent_kafka import Consumer, Producer
import google.generativeai as genai
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from peft import PeftModel
import torch
import re
from urllib.parse import urlparse, parse_qs
from googleapiclient.discovery import build
import time
import os
from google.cloud import secretmanager
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Multilingual Hate Speech Classifier API")

'''
What You Need to Replace:
YOUR_GOOGLE_CLOUD_PROJECT_ID:

Replace with your actual Google Cloud project ID (e.g., "my-project-123456")

Secret Names:

Ensure "GENAI_API_KEY" and "YOUTUBE_API_KEY" match exactly what you named your secrets in Google Secret Manager
'''

def get_secret(secret_id):
    if os.getenv(secret_id):  # Check environment first
        return os.getenv(secret_id)
    
    # Fallback to Secret Manager
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/your-project-id/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode('UTF-8')

genai.configure(api_key=get_secret("GENAI_API_KEY"))
API_KEY = get_secret("YOUTUBE_API_KEY")

# Create Pydantic model for input validation
class VideoInput(BaseModel):
    video_url: str

stored_comments = set()  # Change from list to set

# Configure Kafka consumer and producer
consumer = Consumer({
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'comment-consumer-group',
    'auto.offset.reset': 'earliest'
})
consumer.subscribe(['youtube-comments'])

producer = Producer({'bootstrap.servers': 'localhost:9092'})

# Language and classification dictionaries
dict_of_lang = {0: "Tamil", 1: "Kannada", 2: "Malayalam", 3: "English", 4: "Other"}
dict_of_classification = {0: "Not Hate", 1: "Hate"}

# Load models asynchronously
async def load_models():
    global tamil_model, kannada_model, malayalam_model, tamil_tokenizer, kannada_tokenizer, malayalam_tokenizer

    base_model_name = "google/muril-base-cased"

    tamil_model = AutoModelForSequenceClassification.from_pretrained("sahithimacharapu/tamil-hate-speech-classifier")
    tamil_tokenizer = AutoTokenizer.from_pretrained("sahithimacharapu/tamil-hate-speech-classifier")

    kannada_model = AutoModelForSequenceClassification.from_pretrained("sahithimacharapu/kannada-hate-speech-classifier")
    kannada_tokenizer = AutoTokenizer.from_pretrained("sahithimacharapu/kannada-hate-speech-classifier")

    malayalam_model = AutoModelForSequenceClassification.from_pretrained("sahithimacharapu/malayalam-hate-speech-classifier")
    malayalam_tokenizer = AutoTokenizer.from_pretrained("sahithimacharapu/malayalam-hate-speech-classifier")

# Context manager to manage the lifespan of the app and load models
@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_models()
    yield

app = FastAPI(title="Multilingual Hate Speech Classifier API", lifespan=lifespan)

def detect_language(text):
    model = genai.GenerativeModel('models/gemini-2.0-flash')
    prompt = f"""
    Classify the following text into one of these languages:
    Tamil (0), Kannada (1), Malayalam (2), English (3), Other (4).

    Text: "{text}"

    Provide only the language ID number, without any additional text. For example: "1"
    """
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        match = re.search(r'^\d+$', response_text)
        
        if match:
            return int(match.group(0))
        else:
            return -1
    except Exception as e:
        print(f"Error in language detection: {e}")
        return -1

def classify_text_with_model(model, tokenizer, text):
    from transformers import pipeline
    classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
    result = classifier(text)
    predicted_label_index = int(result[0]["label"].split("_")[1])
    return dict_of_classification[predicted_label_index]

def english_hate_classifier(text):
    model = genai.GenerativeModel('models/gemini-2.0-flash')
    prompt = f"""
    Classify the following English text as offensive speech (1) or not (0).
    Please only respond with '0' for not offensive and '1' for offensive. No other text.

    Text: "{text}"
    
    Classification (0 or 1):
    """
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        if response_text == '0' or response_text == '1':
            return int(response_text)
        else:
            print(f"Unexpected response: {response_text}")
            return -1
    except Exception as e:
        print(f"Error in classification: {e}")
        return -1

def classify_hate(text):
    language_index = detect_language(text)
    if language_index == -1:
        return "Unrecognized Language", "N/A"
    if language_index == 4:
        return "Other Language", "N/A"
    
    language_detected = dict_of_lang.get(language_index, "Unknown")
    if language_detected == "Tamil":
        classification = classify_text_with_model(tamil_model, tamil_tokenizer, text)
    elif language_detected == "Kannada":
        classification = classify_text_with_model(kannada_model, kannada_tokenizer, text)
    elif language_detected == "Malayalam":
        classification = classify_text_with_model(malayalam_model, malayalam_tokenizer, text)
    elif language_detected == "English":
        classification = dict_of_classification[english_hate_classifier(text)]
    else:
        classification = "Unknown"

    return language_detected, classification

async def process_comments():
    global stored_comments
    
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        
        comment_data = json.loads(msg.value().decode('utf-8'))
        comment = comment_data['comment']
        language, classification = classify_hate(comment)
        
        print(f"Classified: {comment} -> Language: {language}, Classification: {classification}")

        if classification == "Hate":
            stored_comments.add((comment, language, classification))
            print(f"Added to stored_comments: {comment}")  # Debugging


def start_kafka_consumer():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(process_comments())

@app.get("/consume")
async def consume_comments():
    thread = Thread(target=start_kafka_consumer)
    thread.start()
    return {"message": "Kafka consumer started"}

@app.get("/")
async def root():
    return {"message": "Multilingual Hate Speech Classifier API"}

@app.post("/process")
async def process_youtube_link(video: VideoInput):
    video_id = extract_video_id(video.video_url)
    
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    print(f"Extracted Video ID: {video_id}")  # Debugging

    # Run Kafka producer script in a separate thread
    thread = Thread(target=stream_comments_to_kafka, args=(video_id,))
    thread.start()

    return {"message": f"Processing started for Video ID: {video_id}. Visit /download to get the CSV file."}


@app.get("/download")
async def download_csv():
    print("Stored Comments:", stored_comments)  # Debugging
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["Comment", "Language", "Classification"])
    
    # Convert set to list and write to CSV
    for comment, language, classification in list(stored_comments):
        writer.writerow([comment, language, classification])
    
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hate_comments.csv"})

def extract_video_id(url):
    parsed_url = urlparse(url)
    
    if parsed_url.netloc in ["www.youtube.com", "youtube.com"]:
        query_params = parse_qs(parsed_url.query)
        return query_params.get("v", [None])[0]
    elif parsed_url.netloc in ["youtu.be"]:
        return parsed_url.path.lstrip("/")
    
    return None

def get_all_youtube_comments(video_id):
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    comments = []
    next_page_token = None

    while True:
        response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText",
            pageToken=next_page_token
        ).execute()

        comments.extend(
            item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            for item in response.get("items", [])
        )

        next_page_token = response.get("nextPageToken")

        if not next_page_token:
            break

    return comments


def stream_comments_to_kafka(video_id):
    seen_comments = set()
    comments = get_all_youtube_comments(video_id)

    for comment in comments:
        if comment not in seen_comments:
            message = json.dumps({"comment": comment})
            producer.produce('youtube-comments', key="comment", value=message)
            seen_comments.add(comment)
            print(f"Sent to Kafka: {comment}")

    producer.flush()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://iitm-team1.vercel.app/", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)