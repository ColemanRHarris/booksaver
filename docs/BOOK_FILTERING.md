# Book Quality & Popularity Filtering

The TikTok Book Finder now includes sophisticated filtering to prioritize popular, trending books that are likely to be featured on BookTok and gaining popularity.

## Filtering Strategy Overview

### 🎯 Target Audience: TikTok BookTok Community
- **Primary Focus**: Recently published, mainstream books
- **Genre Preference**: YA, Romance, Fantasy, Contemporary Fiction  
- **Author Preference**: Popular BookTok authors and viral book series
- **Quality Indicators**: Major publishers, complete metadata, awards/bestseller status

## Multi-Layer Filtering System

### 0. **Language Filtering** (Required)
- **Supported Languages**: English (`en`) and Spanish (`es`) only
- **Detection Methods**: 
  - Google Books language field (highest priority)
  - Publisher-based detection (major English/Spanish publishers)
  - Content analysis (title + description text)
  - Author name patterns (rough heuristics)
- **Confidence Scoring**: 0.0-1.0 based on detection method reliability
- **Filtering**: Books in other languages (German, French, etc.) are excluded

### 1. **Publication Recency Scoring** (20% weight)
- **2022+ (Very Recent)**: 1.0 score - Peak TikTok relevance
- **2019-2021 (Recent)**: 0.8 score - Still highly relevant  
- **2014-2018 (Moderate)**: 0.6 score - Can go viral if rediscovered
- **2004-2013 (Older)**: 0.4 score - Occasional classics
- **Pre-2004**: 0.2 score - Rarely trending

### 2. **Publisher Quality Assessment** (25% weight)
**Major Publishers (1.0 score):**
- Penguin Random House, HarperCollins, Macmillan, Simon & Schuster
- Hachette, Scholastic, Atria, Berkley, Crown, etc.

**Red Flag Publishers (0.1 score):**
- Self-published platforms: CreateSpace, Kindle Direct, Lulu
- Vanity presses: AuthorHouse, Xlibris, iUniverse
- Print-on-demand services

### 3. **Content Popularity Indicators** (20% weight)
**High-Value Keywords:**
- "bestseller", "award winner", "novel", "series", "trilogy"
- "book club", "adaptation", "movie", "Netflix"
- "viral", "trending", "BookTok"

### 4. **BookTok Genre Alignment** (15% weight)
**Top BookTok Genres:**
- Young Adult (YA), Romance, Fantasy
- Contemporary Fiction, Historical Fiction
- Mystery/Thriller, Dystopian, Paranormal
- Dark Academia themes

### 5. **Author Popularity** (10% weight)
**Popular BookTok Authors (Auto-boost):**
- Colleen Hoover, Taylor Jenkins Reid, Emily Henry
- Sarah J. Maas, Leigh Bardugo, Casey McQuiston
- Ali Hazelwood, Rebecca Yarros, Jennifer L. Armentrout

### 6. **Quality Penalties** (Subtractive)
**Heavy Penalties (-0.4 each):**
- Self-published indicators
- Vanity press publishers
- Missing critical metadata

### 7. **Metadata Completeness Bonus** (10% weight)
- Complete book information (title, author, description, ISBN, cover)
- Rich descriptions (100+ characters)
- Professional presentation

## Trending Book Detection

### Viral Book Boost (+0.3 score)
**Known BookTok Viral Books:**
- "It Ends with Us", "Book Lovers", "Beach Read"
- "The Seven Husbands of Evelyn Hugo"
- "A Court of Thorns and Roses", "Six of Crows"
- "Fourth Wing", "From Blood and Ash"
- "The Song of Achilles", "Circe"

### Popular Author Boost (+0.2 score)
Automatically applied when fuzzy matching detects popular BookTok authors.

## Filtering Results

### Quality Threshold
- **Minimum Score**: 0.3 (filters out low-quality books)
- **Maximum Results**: 8 books (focus on highest quality)
- **Score Range**: 0.0 - 1.0 (normalized)

### Expected Outcomes
1. **Self-published books**: Usually filtered out (low publisher score)
2. **Very old books**: Lower scores unless classic/rediscovered
3. **Major publisher + recent + popular author**: High scores (0.8+)
4. **Viral BookTok books**: Maximum scores (1.0)
5. **Academic/niche books**: Lower scores (not trending material)

## Integration Points

### In Main Pipeline (`tasks.py`)
1. OCR extracts potential book titles
2. Fuzzy search finds candidate books
3. **Quality filter** ranks by popularity/trending potential
4. **Trending detector** applies viral book/author boosts
5. **Language filter** ensures only English/Spanish books
6. Final results prioritize BookTok-relevant books in supported languages

### Debug Information
Each filtered book includes:
- `popularity_score`: Overall quality/trending score (0.0-1.0)
- `filter_reasons`: Detailed score breakdown by category
- `trending_boost`: Indication if viral book/author detected
- `detected_language`: Language code (en/es)
- `language_confidence`: Language detection confidence (0.0-1.0)

## Configuration

### Adjustable Parameters
- Quality threshold (currently 0.3)
- Maximum results (currently 8)  
- Publisher lists (can add new major/red-flag publishers)
- Viral book lists (updated as trends change)
- Genre preferences (BookTok evolves)

### Future Enhancements
- Real-time TikTok trending data integration
- Seasonal trend adjustments
- User preference learning
- Regional popularity variations

This filtering system ensures the TikTok Book Finder focuses on books that are most likely to be popular, trending, and relevant to the BookTok community.