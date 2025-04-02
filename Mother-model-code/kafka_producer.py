from confluent_kafka import Producer
from urllib.parse import urlparse, parse_qs
from googleapiclient.discovery import build
import json
import time

# Configure Kafka
producer = Producer({'bootstrap.servers': 'localhost:9092'})

# Configure YouTube API
API_KEY = "AIzaSyD7P0g7cyFfdhLxBJ3RayolCsJt6EJfh54"
YOUTUBE_URL = "https://www.youtube.com/watch?v=af2iFyW3nEY"

def extract_video_id(url):
    """Extracts the video ID from a YouTube URL."""
    parsed_url = urlparse(url)
    
    # Standard YouTube URL
    if parsed_url.netloc in ["www.youtube.com", "youtube.com"]:
        query_params = parse_qs(parsed_url.query)
        return query_params.get("v", [None])[0]
    
    # Shortened YouTube URL
    elif parsed_url.netloc in ["youtu.be"]:
        return parsed_url.path.lstrip("/")
    
    return None

VIDEO_ID = extract_video_id(YOUTUBE_URL)

if not VIDEO_ID:
    raise ValueError("Invalid YouTube URL")

def get_youtube_comments(video_id, max_results=10):
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    
    response = youtube.commentThreads().list(
        part="snippet",
        videoId=video_id,
        maxResults=max_results,
        textFormat="plainText"
    ).execute()
    
    comments = [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in response["items"]
    ]
    return comments

def get_all_youtube_comments(video_id):
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    
    comments = []
    next_page_token = None

    while True:
        response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,  # Maximum allowed value
            textFormat="plainText",
            pageToken=next_page_token
        ).execute()

        comments.extend(
            item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            for item in response.get("items", [])
        )

        next_page_token = response.get("nextPageToken")

        if not next_page_token:
            break  # No more comments to fetch

    return comments

def stream_comments_to_kafka():
    seen_comments = set()
    while True:
        comments = get_all_youtube_comments(VIDEO_ID)
        for comment in comments:
            if comment not in seen_comments:
                message = json.dumps({"comment": comment})
                producer.produce('youtube-comments', key="comment", value=message)
                seen_comments.add(comment)
                print(f"Sent to Kafka: {comment}")
        
        producer.flush()
        time.sleep(30)  # Fetch every 30 seconds

if __name__ == "__main__":
    stream_comments_to_kafka()
