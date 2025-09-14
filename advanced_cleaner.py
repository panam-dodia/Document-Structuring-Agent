import re
from collections import Counter
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class AdvancedTextCleaner:
    def __init__(self, similarity_threshold=0.85):
        self.similarity_threshold = similarity_threshold
        self.vectorizer = TfidfVectorizer(stop_words='english')
    
    def clean_text(self, text):
        """Comprehensive text cleaning"""
        # Basic cleaning
        text = self._remove_extra_whitespace(text)
        text = self._remove_special_characters(text)
        text = self._fix_encoding_issues(text)
        
        # Advanced cleaning
        sentences = self._split_into_sentences(text)
        unique_sentences = self._remove_duplicate_sentences(sentences)
        
        return ' '.join(unique_sentences)
    
    def _remove_extra_whitespace(self, text):
        """Remove extra spaces, tabs, and newlines"""
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _remove_special_characters(self, text):
        """Remove excessive special characters but keep meaningful punctuation"""
        # Keep basic punctuation, remove other special chars
        text = re.sub(r'[^\w\s.,!?;:-]', ' ', text)
        return text
    
    def _fix_encoding_issues(self, text):
        """Fix common encoding problems"""
        replacements = {
            'â€œ': '"', 'â€': '"', 'â€˜': "'", 'â€™': "'",
            'â€”': '—', 'â€“': '–', 'â€¢': '•', 'â„¢': '™',
            'â€¦': '...', '\xa0': ' '
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text
    
    def _split_into_sentences(self, text):
        """Split text into sentences (simplified approach)"""
        # Simple sentence splitting - could be enhanced with nltk if needed
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _remove_duplicate_sentences(self, sentences):
        """Remove duplicate or highly similar sentences using TF-IDF and cosine similarity"""
        if not sentences:
            return []
        
        # Vectorize sentences
        try:
            tfidf_matrix = self.vectorizer.fit_transform(sentences)
            similarity_matrix = cosine_similarity(tfidf_matrix)
            
            # Identify duplicates
            unique_indices = []
            seen_indices = set()
            
            for i in range(len(sentences)):
                if i in seen_indices:
                    continue
                
                unique_indices.append(i)
                # Find similar sentences to this one
                for j in range(i + 1, len(sentences)):
                    if similarity_matrix[i, j] > self.similarity_threshold:
                        seen_indices.add(j)
            
            return [sentences[i] for i in unique_indices]
        
        except Exception:
            # Fallback if TF-IDF fails (e.g., all sentences are too short)
            return list(dict.fromkeys(sentences))  # Remove exact duplicates
    
    def find_and_highlight_duplicates(self, text):
        """Advanced method to identify duplicates for analysis"""
        sentences = self._split_into_sentences(text)
        
        if not sentences:
            return text, []
        
        # Use TF-IDF to find similar sentences
        try:
            tfidf_matrix = self.vectorizer.fit_transform(sentences)
            similarity_matrix = cosine_similarity(tfidf_matrix)
            
            duplicate_groups = []
            processed_indices = set()
            
            for i in range(len(sentences)):
                if i in processed_indices:
                    continue
                
                # Find sentences similar to this one
                similar_indices = [j for j in range(len(sentences)) 
                                 if similarity_matrix[i, j] > self.similarity_threshold and j != i]
                
                if similar_indices:
                    group = [i] + similar_indices
                    duplicate_groups.append([sentences[idx] for idx in group])
                    processed_indices.update(group)
            
            return sentences, duplicate_groups
        
        except Exception:
            return sentences, []