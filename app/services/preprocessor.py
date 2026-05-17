import re
import unicodedata
from pyvi import ViTokenizer
from typing import Set

class VietnamesePreprocessor:
    def __init__(self, stopwords_file=None):
        self.stopwords = set()
        if stopwords_file:
            try:
                with open(stopwords_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        self.stopwords.add(line.strip())
            except Exception as e:
                print(f"Warning: Could not load stopwords from {stopwords_file}: {e}")

    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        
        # 1. Normalize encoding (NFC)
        text = unicodedata.normalize('NFC', text)
        
        # 2. Lowercase
        text = text.lower()
        
        # 3. Remove HTML tags
        text = re.sub(r'<.*?>', '', text)
        
        # 4. Remove special characters (keeping essential Vietnamese chars and basic punctuation)
        text = re.sub(r'[^a-zA-Z0-9\sàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', '', text)
        
        # 5. Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 6. Word Segmentation (PhoBERT style)
        text = ViTokenizer.tokenize(text)
        
        # 7. Stopword removal
        if self.stopwords:
            words = text.split()
            words = [str(w) for w in words if w not in self.stopwords]
            text = " ".join(words)
            
        return text

preprocessor = VietnamesePreprocessor()
