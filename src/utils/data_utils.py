import sqlite3
import re
from pathlib import Path
from typing import Optional

def get_db_connection(db_path: str) -> sqlite3.Connection:
    """
    Establishes a connection to the SQLite database.
    
    Args:
        db_path (str): Path to the SQLite database file.
        
    Returns:
        sqlite3.Connection: Connection object to the database.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn
    except sqlite3.Error as e:
        raise ConnectionError(f"Error connecting to database at {db_path}: {e}")

def calculate_cs_ratio(text: str) -> float:
    """
    Crudely estimates the ratio of English words in a Vietnamese-English sentence.
    
    Logic:
    - Tokenizes text by whitespace.
    - Identifies Vietnamese words by the presence of specific Vietnamese characters (diacritics).
    - Treats everything else as potentially English.
    
    Args:
        text (str): The code-switched input text.
        
    Returns:
        float: Percentage of English words (0.0 to 1.0).
    """
    if not text or not text.strip():
        return 0.0

    # Regex for Vietnamese specific characters (including lower and upper case)
    # Matches: àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ
    vn_chars_pattern = re.compile(r'[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', re.IGNORECASE)
    
    words = text.strip().split()
    total_words = len(words)
    
    if total_words == 0:
        return 0.0
        
    english_like_count = 0
    
    for word in words:
        # Remove punctuation for cleaner check
        clean_word = re.sub(r'[^\w\s]', '', word)
        
        # Skip if the word became empty after removing punctuation (e.g. just a comma)
        if not clean_word:
            total_words -= 1
            continue
            
        # If it contains Vietnamese characters, it's Vietnamese.
        # If it doesn't, we count it as English (per crude heuristic).
        if not vn_chars_pattern.search(clean_word):
            english_like_count += 1
            
    if total_words == 0:
        return 0.0
    
    return round(english_like_count / total_words, 2)
