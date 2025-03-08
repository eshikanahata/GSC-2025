import numpy as np 
import pandas as pd
from ai4bharat.transliteration import XlitEngine
import pandas as pd
import re
import torch
from langdetect import detect

# Initialize the transliteration engine
engine = XlitEngine("kn", beam_width=4, rescore=True)

# Function to split text into words
def split_into_words(text):
    return re.findall(r'\b\w+\b', text)

# Function to transliterate text with code-mixing awareness
def transliterate_code_mixed(text):
    # If text is already in Kannada script, return as is
    if any('\u0C80' <= char <= '\u0CFF' for char in text):
        return text
    
    # Try to detect language
    try:
        lang = detect(text)
    except Exception as e:
        print(f"Language detection error: {e}")
        return text

    if lang == 'en':
        # If clearly English, transliterate the whole text
        try:
            result = engine.translit_sentence(text)
            return result['kn']
        except Exception as e:
            print(f"Transliteration error: {e}")
            return text
    
    # For code-mixed text, process word by word
    words = split_into_words(text)
    transliterated_words = []
    
    for word in words:
        # Skip English words that shouldn't be transliterated
        if word.isdigit() or (len(word) <= 2 and word.isalpha() and word.isupper()):
            transliterated_words.append(word)
        else:
            try:
                result = engine.translit_word(word)
                transliterated_words.append(result['kn'][0])
            except Exception as e:
                transliterated_words.append(word)
    
    # Reconstruct the text with proper spacing and punctuation
    pattern = re.compile(r'(\b\w+\b)')
    result = pattern.sub(lambda x: transliterated_words.pop(0) if transliterated_words else x.group(), text)
    return result

# Load your dataset
try:
    df = pd.read_csv('kannada_dataset_0.csv')
except Exception as e:
    print(f"Error loading dataset: {e}")
    df = pd.DataFrame()

# Apply transliteration if the dataset is loaded successfully
if not df.empty:
    try:
        df['kannada_script'] = df['comment'].apply(transliterate_code_mixed)
        # Save the updated dataset
        df.to_csv('kannada_dataset_0_transliterated.csv', index=False)
        print("Transliteration completed!")
    except Exception as e:
        print(f"Error during transliteration process: {e}")
else:
    print("Dataset is empty or not loaded properly.")