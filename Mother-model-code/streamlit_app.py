'''

import streamlit as st
import requests
import time

# FastAPI Base URL (Update if hosted on a server)
FASTAPI_URL = "http://127.0.0.1:8000"

st.title("Hate Speech Comment Classifier")

# Input field for YouTube URL
video_url = st.text_input("Enter YouTube Video URL:")

# Button to start processing
if st.button("Process Video"):
    if video_url:
        with st.spinner("Processing comments... Please wait!"):
            response = requests.post(f"{FASTAPI_URL}/process", json={"video_url": video_url})

        if response.status_code == 200:
            st.success(response.json().get("message", "Processing started!"))
        else:
            error_message = response.json().get("detail", "An error occurred.")
            st.error(f"Error: {error_message}")
    else:
        st.warning("Please enter a valid YouTube video URL.")

# Wait time to ensure comments are processed
time.sleep(10)  # Adjust based on processing time

# Button to download CSV file
if st.button("Download Hate Comments CSV"):
    with st.spinner("Fetching hate comments..."):
        response = requests.get(f"{FASTAPI_URL}/download")

    if response.status_code == 200:
        st.download_button(
            label="Download CSV",
            data=response.content,
            file_name="hate_comments.csv",
            mime="text/csv"
        )
        st.success("Download ready!")
    else:
        st.error("Failed to download the CSV file. Make sure the video has been processed first.")
'''
import streamlit as st
import requests
import time

# FastAPI Base URL
FASTAPI_URL = "http://127.0.0.1:8000"

st.title("Hate Speech Comment Classifier")

# Input for YouTube video URL
video_url = st.text_input("Enter YouTube Video URL:")

# Button to start processing
if st.button("Process Video"):
    if video_url:
        with st.spinner("Starting processing..."):
            response = requests.post(f"{FASTAPI_URL}/process", json={"video_url": video_url})

        if response.status_code == 200:
            st.success(response.json().get("message", "Processing started!"))

            # Start Kafka consumer to process hate speech classification
            with st.spinner("Waiting for comments to be classified..."):
                consume_response = requests.get(f"{FASTAPI_URL}/consume")
                if consume_response.status_code == 200:
                    st.success("Comment classification started!")
                else:
                    st.warning("Failed to start comment classification.")

        else:
            error_message = response.json().get("detail", "An error occurred.")
            st.error(f"Error: {error_message}")
    else:
        st.warning("Please enter a valid YouTube video URL.")

# Wait to allow processing before downloading
time.sleep(15)  # Adjust based on your Kafka pipeline speed

# Button to download CSV file
if st.button("Download Hate Comments CSV"):
    with st.spinner("Fetching hate comments..."):
        response = requests.get(f"{FASTAPI_URL}/download")

    if response.status_code == 200:
        st.download_button(
            label="Download CSV",
            data=response.content,
            file_name="hate_comments.csv",
            mime="text/csv"
        )
        st.success("Download ready!")
    else:
        st.error("Failed to download the CSV file. Ensure processing is complete.")
