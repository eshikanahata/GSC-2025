import streamlit as st
import requests

# FastAPI base URL
FASTAPI_URL = "http://127.0.0.1:8000"

st.title("Hate Speech Comment Classifier")

# Input for YouTube video URL
video_url = st.text_input("Enter YouTube Video URL:")

if st.button("Process Video"):
    if video_url:
        # Send POST request to FastAPI /process endpoint
        response = requests.post(f"{FASTAPI_URL}/process", json={"video_url": video_url})
        if response.status_code == 200:
            st.success(response.json().get("message", "Processing started!"))
        else:
            st.error(response.json().get("detail", "An error occurred."))
    else:
        st.warning("Please enter a valid YouTube video URL.")

# Button to download the CSV file
if st.button("Download Hate Comments CSV"):
    response = requests.get(f"{FASTAPI_URL}/download")
    if response.status_code == 200:
        # Provide the CSV file for download
        st.download_button(
            label="Download CSV",
            data=response.content,
            file_name="hate_comments.csv",
            mime="text/csv"
        )
    else:
        st.error("Failed to download the CSV file.")