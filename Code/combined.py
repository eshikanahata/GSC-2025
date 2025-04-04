from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio
import csv
import io
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import google.generativeai as genai
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
import re
from urllib.parse import urlparse, parse_qs
from googleapiclient.discovery import build
import os
from google.cloud import secretmanager
from dotenv import load_dotenv

# Load environment variables from .env file (local development only)
if os.path.exists('.env'):
    load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Multilingual Hate Speech Classifier API")

# Replace with your actual Google Cloud project ID
PROJECT_ID = "arcane-firefly-455806-a8"

def get_secret(secret_id):
    if os.getenv(secret_id):  # Check environment first
        return os.getenv(secret_id)
    
    # Fallback to Secret Manager
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(name=name)
        return response.payload.data.decode('UTF-8')
    except Exception as e:
        print(f"Error retrieving secret {secret_id}: {e}")
        return None

# Set up API keys
genai_api_key = get_secret("GENAI_API_KEY")
youtube_api_key = get_secret("YOUTUBE_API_KEY")

if genai_api_key:
    genai.configure(api_key=genai_api_key)

# Create Pydantic model for input validation
class VideoInput(BaseModel):
    video_url: str

# For storing comments (in-memory for demonstration)
# In production, use a database or Cloud Storage
stored_comments = set()  

# Language and classification dictionaries
dict_of_lang = {0: "Tamil", 1: "Kannada", 2: "Malayalam", 3: "English", 4: "Other"}
dict_of_classification = {0: "Not Hate", 1: "Hate"}

# Global variables for models and tokenizers
tamil_model = None
kannada_model = None
malayalam_model = None
tamil_tokenizer = None
kannada_tokenizer = None
malayalam_tokenizer = None

# Load models asynchronously
async def load_models():
    global tamil_model, kannada_model, malayalam_model, tamil_tokenizer, kannada_tokenizer, malayalam_tokenizer

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
    if not genai_api_key:
        raise HTTPException(status_code=500, detail="GENAI_API_KEY not configured")
        
    model = genai.GenerativeModel('models/gemini-2.0-flash')
    prompt = f'''
    Classify the following text into one of these languages:
    Tamil (0), Kannada (1), Malayalam (2), English (3), Other (4).

    Text: "{text}"

    Provide only the language ID number, without any additional text. For example: "1"
    '''
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
    classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
    result = classifier(text)
    predicted_label_index = int(result[0]["label"].split("_")[1])
    return dict_of_classification[predicted_label_index]

def english_hate_classifier(text):
    if not genai_api_key:
        raise HTTPException(status_code=500, detail="GENAI_API_KEY not configured")
        
    model = genai.GenerativeModel('models/gemini-2.0-flash')
    prompt = f'''
    Classify the following English text as offensive speech (1) or not (0).
    Please only respond with '0' for not offensive and '1' for offensive. No other text.

    Text: "{text}"
    
    Classification (0 or 1):
    '''
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

@app.get("/")
async def root():
    return {"message": "Multilingual Hate Speech Classifier API"}

@app.post("/classify-comment")
async def classify_single_comment(text: str):
    language, classification = classify_hate(text)
    
    if classification == "Hate":
        stored_comments.add((text, language, classification))
        
    return {
        "text": text,
        "language": language,
        "classification": classification
    }

@app.post("/process")
async def process_youtube_link(video: VideoInput):
    if not youtube_api_key:
        raise HTTPException(status_code=500, detail="YOUTUBE_API_KEY not configured")
        
    video_id = extract_video_id(video.video_url)
    
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    print(f"Extracted Video ID: {video_id}")
    
    # Process comments directly instead of using Kafka
    comments = get_all_youtube_comments(video_id)
    
    for comment in comments:
        language, classification = classify_hate(comment)
        if classification == "Hate":
            stored_comments.add((comment, language, classification))
    
    return {
        "message": f"Processed {len(comments)} comments for Video ID: {video_id}. Visit /download to get the CSV file.",
        "hate_comments_found": len(stored_comments)
    }

@app.get("/download")
async def download_csv():
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
    youtube = build('youtube', 'v3', developerKey=youtube_api_key)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with your actual frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
