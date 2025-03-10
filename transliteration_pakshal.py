import pandas as pd
import re
import emoji
from google.transliteration.transliterate import transliterate_text
from langdetect import detect

def split_into_words(text):
    return re.findall(r'\b\w+\b', text)

def transliterate_code_mixed(text):
    print('.', end='', flush=True)
    text = emoji.demojize(text)
    if any('\u0D00' <= char <= '\u0D7F' for char in text):
        return text
    words = split_into_words(text)
    converted = ''
    for word in words:
        try:
            lang = detect(word)
        except:
            lang = ''
        if word.isdigit() or lang == 'en':
            converted += word + ' '
        else:
            try:
                converted += transliterate_text(word, 'ml') + ' '
            except:
                print(word)
                converted += word
    return converted

# Load your dataset
df = pd.read_csv('malyalam_dataset_1.csv')
df['malyalam_script'] = df['comment'].apply(transliterate_code_mixed)
df.to_csv('malyalam_dataset_1_transliterated.csv', index=False)