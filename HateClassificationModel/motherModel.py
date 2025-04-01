from fastapi import FastAPI, HTTPException
from confluent_kafka import Consumer
from contextlib import asynccontextmanager
from pydantic import BaseModel
import json
import google.generativeai as genai
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from peft import PeftModel
import torch
import os
import asyncio
from threading import Thread
import re
import csv

# Initialize FastAPI
app = FastAPI(title="Multilingual Hate Speech Classifier API")
genai.configure(api_key="AIzaSyDtK8u-GXS5INUJAW38fr2-5ya1RsUwStg")

# Path to your CSV file
csv_file_path = "classified_hate_comments.csv"

# Write header to CSV if the file is empty or doesn't exist
def write_to_csv(comment, language, classification):
    # Check if the file exists or not, and write the header if it's the first entry
    file_exists = os.path.isfile(csv_file_path)
    
    with open(csv_file_path, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        if not file_exists:
            # Write header if file is new or empty
            writer.writerow(['Comment', 'Language', 'Classification'])
        
        # Write the classified comment
        writer.writerow([comment, language, classification])

# Define input/output models
class ClassificationOutput(BaseModel):
    language: str
    classification: str

# Kafka Consumer Config
consumer = Consumer({
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'comment-consumer-group',
    'auto.offset.reset': 'earliest'
})
consumer.subscribe(['youtube-comments'])

# Configure Dictionaries
dict_of_lang = {0: "Tamil", 1: "Kannada", 2: "Malayalam", 3: "English", 4: "Other"}
dict_of_classification = {0: "Not Hate", 1: "Hate"}

# Load models
async def load_models():
    global tamil_model, kannada_model, malayalam_model, tamil_tokenizer, kannada_tokenizer, malayalam_tokenizer
    
    base_model_name = "google/muril-base-cased"

    # Tamil model
    tamil_model = AutoModelForSequenceClassification.from_pretrained(base_model_name)
    tamil_adapter_path = "/Users/anitha/Downloads/mother_model.py/tamil-comment-classifier"
    tamil_model = PeftModel.from_pretrained(tamil_model, tamil_adapter_path)
    tamil_tokenizer = AutoTokenizer.from_pretrained(base_model_name)

    # Kannada model
    kannada_model = AutoModelForSequenceClassification.from_pretrained(base_model_name)
    kannada_adapter_path = "/Users/anitha/Downloads/mother_model.py/kannada-comment-classifier"
    kannada_model = PeftModel.from_pretrained(kannada_model, kannada_adapter_path)
    kannada_tokenizer = AutoTokenizer.from_pretrained(base_model_name)

    # Malayalam model
    malayalam_model = AutoModelForSequenceClassification.from_pretrained(base_model_name)
    malayalam_adapter_path = "/Users/anitha/Downloads/mother_model.py/malayalam-comment-classifier"
    malayalam_model = PeftModel.from_pretrained(malayalam_model, malayalam_adapter_path)
    malayalam_tokenizer = AutoTokenizer.from_pretrained(base_model_name)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_models()
    yield

app = FastAPI(title="Multilingual Hate Speech Classifier API", lifespan=lifespan)

# Detect language
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
        print(f"Raw model response: {response_text}")  # Check the raw response
        
        # Extract the number (language ID) from the response using regex
        # This will ensure only the number is extracted
        match = re.search(r'^\d+$', response_text)  # Match a string with only digits
        
        if match:
            return int(match.group(0))  # Return the number found
        else:
            return -1  # Return -1 if the response is not just a number
    except Exception as e:
        print(f"Error in language detection: {e}")
        return -1

# Classify text
def classify_text_with_model(model, tokenizer, text):
    from transformers import pipeline
    classifier = pipeline("text-classification", model=model, tokenizer=tokenizer)
    result = classifier(text)
    predicted_label_index = int(result[0]["label"].split("_")[1])
    return dict_of_classification[predicted_label_index]

# Classify English text
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
        
        # Ensure the response is either '0' or '1'
        if response_text == '0' or response_text == '1':
            return int(response_text)  # Return as integer
        else:
            print(f"Unexpected response: {response_text}")
            return -1  # Return -1 if the response isn't '0' or '1'
    except Exception as e:
        print(f"Error in classification: {e}")
        return -1

# Core classification function
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

# Kafka Consumer Function (non-blocking)
async def process_comments():
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        
        comment_data = json.loads(msg.value().decode('utf-8'))
        comment = comment_data['comment']
        language, classification = classify_hate(comment)
        
        print(f"Classified: {comment} -> Language: {language}, Classification: {classification}")

        if classification == "Hate":
            write_to_csv(comment, language, classification)

# Run the Kafka consumer in a separate thread
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

# Run FastAPI
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://iitm-team1.vercel.app/", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)