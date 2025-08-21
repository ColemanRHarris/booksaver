"""
Fuzzy matching system for handling near-miss OCR results when searching books
"""

from fuzzywuzzy import fuzz, process
from typing import List, Dict, Any, Optional
from datetime import datetime
import re
from books_client import GoogleBooksClient
import time

class FuzzyBookSearcher:
    """Enhanced book searcher with fuzzy matching capabilities"""
    
    def __init__(self, books_client: GoogleBooksClient):
        self.books_client = books_client
        # Cache of common OCR corrections
        self.ocr_corrections = {
            # Common letter substitutions
            '0': 'O',
            '1': 'I',
            '5': 'S', 
            '8': 'B',
            '6': 'G',
            'rn': 'm',
            'cl': 'd',
            'vv': 'w',
            'ii': 'n',
            'll': 'n',
            # Add more as we discover patterns
        }
    
    def search_with_fuzzy_fallback(self, ocr_text: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """
        Search for books with fuzzy matching fallback for near-miss OCR results
        """
        print(f"🔍 Fuzzy search for: '{ocr_text}'")
        
        # Step 1: Try exact search first
        exact_results = self.books_client.search_books(ocr_text, max_results)
        if exact_results:
            print(f"✅ Found {len(exact_results)} exact matches")
            return exact_results
        
        # Step 2: Try corrected OCR text
        #corrected_text = self._apply_ocr_corrections(ocr_text)
        #if corrected_text != ocr_text:
        #    print(f"🔧 Trying OCR corrections: '{ocr_text}' -> '{corrected_text}'")
        #    corrected_results = self.books_client.search_books(corrected_text, max_results)
        #    if corrected_results:
        #        print(f"✅ Found {len(corrected_results)} matches with corrections")
        #        return corrected_results
        
        # Step 3: Initialize results collection
        #all_fuzzy_results = []
        
        # Try individual words (authors/titles often split)
        #words = ocr_text.split()
        #if len(words) >= 2:
        #    print(f"🔍 Trying individual words from: '{ocr_text}'")
        #    for word in words:
        #        if len(word) >= 4:  # Skip very short words
        #            word_results = self.books_client.search_books(word, max_results=2)
        #            for result in word_results:
        #                fuzzy_score = self._score_fuzzy_match(ocr_text, result.get('title', ''), result.get('authors', []))
        #                if fuzzy_score > 0.5:  # Only good matches
        #                    result['fuzzy_match_score'] = fuzzy_score
        #                    result['fuzzy_query'] = word
        #                    all_fuzzy_results.append(result)
        #            time.sleep(0.3)
        
        # Step 4: Try fuzzy variations with early termination
        #fuzzy_variations = self._generate_fuzzy_variations(ocr_text)
        #print(f"🎯 Trying {len(fuzzy_variations)} fuzzy variations...")
        #high_quality_matches = []
        
        #for i, variation in enumerate(fuzzy_variations):
        #    if i > 0:  # Rate limiting
        #        time.sleep(0.3)
        #    
        #    print(f"  {i+1}. '{variation}'")
        #    results = self.books_client.search_books(variation, max_results=2)  # Smaller for variations
        #    
        #    for result in results:
        #        # Score the fuzzy match
        #        fuzzy_score = self._score_fuzzy_match(ocr_text, result.get('title', ''), result.get('authors', []))
        #        result['fuzzy_match_score'] = fuzzy_score
        #        result['fuzzy_query'] = variation
        #        all_fuzzy_results.append(result)
        #        
        #        # Track high quality matches for early termination
        #        if fuzzy_score > 0.8:
        #            high_quality_matches.append(result)
        #    
        #    if results:
        #        print(f"    → Found {len(results)} results")
        #    
        #    # Early termination if we found good matches
        #    if len(high_quality_matches) >= 2:
        #        print(f"🎯 Early termination: Found {len(high_quality_matches)} high-quality matches (score > 0.8)")
        #        break
        
        # Sort by fuzzy match score and remove duplicates
        #unique_results = self._deduplicate_results(all_fuzzy_results)
        #unique_results.sort(key=lambda x: x.get('fuzzy_match_score', 0), reverse=True)
        
        # Return top matches
        #final_results = unique_results[:max_results]
        #if final_results:
        #    scores = [f"{r.get('fuzzy_match_score', 0):.2f}" for r in final_results]
        #    print(f"🎉 Best fuzzy matches (scores: {scores})")
        #    for r in final_results:
        #        print(f"  - '{r.get('title', 'Unknown')}' (query: '{r.get('fuzzy_query', '')}')")
        
        return []
    
    def _apply_ocr_corrections(self, text: str) -> str:
        """Apply common OCR error corrections"""
        corrected = text
        
        # Apply character-level corrections
        for wrong, correct in self.ocr_corrections.items():
            corrected = corrected.replace(wrong, correct)
        
        # Fix common word-level OCR errors (expanded list)
        word_corrections = {
            'ZERD': 'ZERO',
            'ZERE': 'ZERO', 
            'MCHELLE': 'MICHELLE',
            'MICHELL': 'MICHELLE',
            'MICHEAL': 'MICHAEL',
            'STEELING': 'STERLING',
            'STELLING': 'STERLING',
            'STERING': 'STERLING',
            'STERUNG': 'STERLING',
            'TIITLE': 'TITLE',
            'AUTHER': 'AUTHOR',
            'AUTHUR': 'AUTHOR',
            # Common OCR mixups
            'FURST': 'FIRST',
            'NUGHT': 'NIGHT',
            'CUGHT': 'CAUGHT',
            'LUGHT': 'LIGHT',
            'RUGHT': 'RIGHT',
            'BUGHT': 'BOUGHT',
        }
        
        words = corrected.split()
        corrected_words = []
        for word in words:
            corrected_word = word_corrections.get(word.upper(), word)
            corrected_words.append(corrected_word)
        
        return ' '.join(corrected_words)
    
    def _generate_fuzzy_variations(self, text: str) -> List[str]:
        """Generate variations of the text for fuzzy searching"""
        variations = []
        
        # Original text
        variations.append(text)
        
        # Apply OCR corrections
        corrected = self._apply_ocr_corrections(text)
        if corrected != text:
            variations.append(corrected)
        
        # Word reordering variations (common with OCR)
        words = text.split()
        if len(words) >= 2:
            # Try different word orders
            variations.append(' '.join(reversed(words)))  # Reverse order
            
            # For author names, try "First Last" and "Last First" patterns
            if len(words) == 2:
                variations.append(f"{words[1]} {words[0]}")
            elif len(words) == 3:
                # Try different arrangements for 3 words
                variations.extend([
                    f"{words[2]} {words[0]} {words[1]}",
                    f"{words[1]} {words[2]} {words[0]}",
                    f"{words[0]} {words[2]} {words[1]}",
                ])
        
        # Character-level fuzzy variations for short corrections
        if len(text) <= 20:  # Only for shorter texts
            # Try dropping last character (common OCR issue)
            if len(text) > 3:
                variations.append(text[:-1])
            
            # Try common single-character substitutions (expanded)
            char_substitutions = [
                ('O', '0'), ('0', 'O'),
                ('I', '1'), ('1', 'I'), ('I', 'l'), ('l', 'I'),
                ('S', '5'), ('5', 'S'),
                ('B', '8'), ('8', 'B'),
                ('D', 'O'), ('O', 'D'),
                ('C', 'G'), ('G', 'C'),
                ('F', 'P'), ('P', 'F'),
                ('H', 'N'), ('N', 'H'),
                ('E', 'F'), ('F', 'E'),
                ('U', 'V'), ('V', 'U'),
                ('W', 'VV'), ('VV', 'W'),
                ('M', 'N'), ('N', 'M'),
                ('R', 'B'), ('B', 'R'),
            ]
            
            for wrong, correct in char_substitutions:
                if wrong in text:
                    variations.append(text.replace(wrong, correct))
        
        # Remove duplicates while preserving order
        unique_variations = []
        seen = set()
        for var in variations:
            var_clean = var.strip().lower()
            if var_clean not in seen and len(var.strip()) > 2:
                unique_variations.append(var.strip())
                seen.add(var_clean)
        
        # Limit to reasonable number to avoid rate limiting
        return unique_variations[:4]
    
    def _score_fuzzy_match(self, ocr_text: str, book_title: str, book_authors: List[str]) -> float:
        """Score how well a book matches the OCR text using fuzzy matching"""
        ocr_lower = ocr_text.lower().strip()
        title_lower = book_title.lower().strip()
        
        # Title similarity (most important)
        title_ratio = fuzz.ratio(ocr_lower, title_lower) / 100.0
        title_partial = fuzz.partial_ratio(ocr_lower, title_lower) / 100.0
        title_token_sort = fuzz.token_sort_ratio(ocr_lower, title_lower) / 100.0
        title_token_set = fuzz.token_set_ratio(ocr_lower, title_lower) / 100.0
        
        # Take best title matching score
        title_score = max(title_ratio, title_partial, title_token_sort, title_token_set)
        
        # Author similarity (if OCR text might contain author)
        author_score = 0.0
        if book_authors:
            for author in book_authors:
                author_lower = author.lower().strip()
                author_ratio = fuzz.partial_ratio(ocr_lower, author_lower) / 100.0
                author_token = fuzz.token_set_ratio(ocr_lower, author_lower) / 100.0
                author_score = max(author_score, author_ratio, author_token)
        
        # Combined title + author matching (OCR might have both)
        combined_text = f"{book_title} {' '.join(book_authors)}".lower().strip()
        combined_ratio = fuzz.token_set_ratio(ocr_lower, combined_text) / 100.0
        combined_partial = fuzz.partial_ratio(ocr_lower, combined_text) / 100.0
        combined_score = max(combined_ratio, combined_partial)
        
        # Weight the scores
        # Title match is most important, but author and combined can boost score
        final_score = (title_score * 0.6 + 
                      author_score * 0.2 + 
                      combined_score * 0.2)
        
        return final_score
    
    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate books from results"""
        seen_titles = set()
        unique_results = []
        
        for result in results:
            title = result.get('title', '').lower().strip()
            # Create a key with title + first author for deduplication
            authors = result.get('authors', [])
            author_key = authors[0].lower().strip() if authors else ""
            key = f"{title}|{author_key}"
            
            if key not in seen_titles:
                seen_titles.add(key)
                unique_results.append(result)
        
        return unique_results

def create_fuzzy_searcher() -> FuzzyBookSearcher:
    """Create a fuzzy searcher instance"""
    books_client = GoogleBooksClient()
    return FuzzyBookSearcher(books_client)