"""
Semantic Search Engine for AI Tools Hub

Uses sentence-transformers for local embedding generation and numpy for
similarity search. Implements hybrid search combining semantic similarity
with keyword matching.
"""

import os
import json
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from functools import lru_cache
import threading

# Global engine instance (lazy loaded)
_engine_instance = None
_engine_lock = threading.Lock()


def get_search_engine():
    """Get or create the global semantic search engine instance"""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = SemanticSearchEngine()
    return _engine_instance


class SemanticSearchEngine:
    """
    Semantic search engine using sentence-transformers.
    
    Uses in-memory numpy arrays for vector storage (suitable for SQLite/dev).
    For production with PostgreSQL, consider upgrading to pgvector.
    """
    
    # Model to use for embeddings
    MODEL_NAME = 'all-MiniLM-L6-v2'
    EMBEDDING_DIM = 384  # Dimension of all-MiniLM-L6-v2 embeddings
    
    def __init__(self):
        self._model = None
        self._embeddings_cache: Dict[int, np.ndarray] = {}
        self._tools_cache: Dict[int, dict] = {}
        self._cache_loaded = False
        self._model_load_lock = threading.Lock()
        
    @property
    def model(self):
        """Lazy load the sentence-transformer model"""
        if self._model is None:
            with self._model_load_lock:
                if self._model is None:
                    print(f"🔄 Loading sentence-transformers model: {self.MODEL_NAME}")
                    try:
                        from sentence_transformers import SentenceTransformer
                        self._model = SentenceTransformer(self.MODEL_NAME)
                        print(f"✅ Model loaded successfully")
                    except ImportError:
                        print("❌ sentence-transformers not installed. Run: pip install sentence-transformers")
                        raise
        return self._model
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for given text.
        
        Args:
            text: Input text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        if not text or not text.strip():
            return [0.0] * self.EMBEDDING_DIM
            
        # Clean and normalize text
        text = text.strip()[:2000]  # Limit text length for efficiency
        
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def embedding_to_json(self, embedding: List[float]) -> str:
        """Convert embedding to JSON string for database storage"""
        return json.dumps(embedding)
    
    def embedding_from_json(self, json_str: str) -> np.ndarray:
        """Load embedding from JSON string"""
        if not json_str:
            return np.zeros(self.EMBEDDING_DIM)
        return np.array(json.loads(json_str))
    
    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors"""
        if np.linalg.norm(vec1) == 0 or np.linalg.norm(vec2) == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
    
    def load_tool_embeddings(self, force_reload: bool = False):
        """
        Load all tool embeddings from database into memory cache.
        
        Args:
            force_reload: If True, reload even if cache is populated
        """
        if self._cache_loaded and not force_reload:
            return
            
        # Import here to avoid circular imports
        from app import app
        from models import db, Tool
        
        with app.app_context():
            tools = Tool.query.all()
            
            for tool in tools:
                # Cache tool data
                self._tools_cache[tool.id] = {
                    'id': tool.id,
                    'name': tool.name,
                    'description': tool.description,
                    'short_description': tool.short_description,
                    'category': tool.category,
                    'rating': tool.rating,
                    'review_count': tool.review_count,
                    'pricing': tool.pricing,
                    'website': tool.website,
                    'logo': tool.logo,
                    'tags': tool.tags,
                    'features': tool.features
                }
                
                # Load or generate embedding
                if hasattr(tool, 'embedding') and tool.embedding:
                    self._embeddings_cache[tool.id] = self.embedding_from_json(tool.embedding)
                else:
                    # Generate embedding on-the-fly if not stored
                    searchable_text = self._get_searchable_text(tool)
                    embedding = self.generate_embedding(searchable_text)
                    self._embeddings_cache[tool.id] = np.array(embedding)
            
            self._cache_loaded = True
            print(f"✅ Loaded {len(self._embeddings_cache)} tool embeddings into cache")
    
    def _get_searchable_text(self, tool) -> str:
        """Generate searchable text from tool fields"""
        parts = []
        
        if tool.name:
            parts.append(tool.name)
        if tool.short_description:
            parts.append(tool.short_description)
        if tool.description:
            parts.append(tool.description[:500])  # Limit description length
        if tool.category:
            parts.append(f"Category: {tool.category}")
        
        # Parse tags if stored as JSON
        if tool.tags:
            try:
                if tool.tags.startswith('['):
                    tags = json.loads(tool.tags)
                else:
                    tags = [t.strip() for t in tool.tags.split(',')]
                parts.append(f"Tags: {', '.join(tags)}")
            except:
                parts.append(f"Tags: {tool.tags}")
        
        return ' '.join(parts)
    
    def semantic_search(
        self, 
        query: str, 
        limit: int = 10,
        min_score: float = 0.0
    ) -> List[Tuple[dict, float]]:
        """
        Perform pure semantic search using cosine similarity.
        
        Args:
            query: Search query text
            limit: Maximum number of results
            min_score: Minimum similarity score (0-1)
            
        Returns:
            List of (tool_dict, score) tuples, sorted by score descending
        """
        # Ensure embeddings are loaded
        self.load_tool_embeddings()
        
        if not self._embeddings_cache:
            return []
        
        # Generate query embedding
        query_embedding = np.array(self.generate_embedding(query))
        
        # Calculate similarity scores for all tools
        scores = []
        for tool_id, tool_embedding in self._embeddings_cache.items():
            similarity = self.cosine_similarity(query_embedding, tool_embedding)
            if similarity >= min_score:
                scores.append((tool_id, similarity))
        
        # Sort by similarity score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return top results with tool data
        results = []
        for tool_id, score in scores[:limit]:
            tool_data = self._tools_cache.get(tool_id)
            if tool_data:
                results.append((tool_data, score))
        
        return results
    
    def keyword_search(
        self, 
        query: str, 
        limit: int = 10
    ) -> List[Tuple[dict, float]]:
        """
        Perform keyword search with term frequency scoring.
        Prioritizes category and tag matches for better relevance.
        
        Args:
            query: Search query text
            limit: Maximum number of results
            
        Returns:
            List of (tool_dict, score) tuples
        """
        # Ensure data is loaded
        self.load_tool_embeddings()
        
        if not self._tools_cache:
            return []
        
        query_terms = query.lower().split()
        
        scores = []
        for tool_id, tool_data in self._tools_cache.items():
            score = 0.0
            
            name = tool_data.get('name', '').lower()
            short_desc = tool_data.get('short_description', '').lower()
            description = tool_data.get('description', '').lower()
            category = tool_data.get('category', '').lower()
            tags = tool_data.get('tags', '').lower()
            
            # Score based on term presence - prioritize category and tags
            for term in query_terms:
                # Category match is very important (e.g., "image" -> Image category)
                if term in category:
                    score += 5.0
                
                # Tag match is very important (e.g., "editing" -> "image-editing" tag)
                if term in tags:
                    score += 4.0
                
                # Name match is important
                if term in name:
                    score += 3.0
                
                # Short description match
                if term in short_desc:
                    score += 2.0
                
                # Full description match (less weight)
                if term in description:
                    score += 1.0
            
            # Bonus: if BOTH query terms match category/tags, give extra boost
            category_tag_matches = sum(1 for term in query_terms if term in category or term in tags)
            if category_tag_matches >= 2:
                score += 3.0
            
            if score > 0:
                scores.append((tool_id, score))
        
        # Normalize scores to 0-1 range
        if scores:
            max_score = max(s[1] for s in scores)
            if max_score > 0:
                scores = [(tid, s / max_score) for tid, s in scores]
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return top results with tool data
        results = []
        for tool_id, score in scores[:limit]:
            tool_data = self._tools_cache.get(tool_id)
            if tool_data:
                results.append((tool_data, score))
        
        return results
    
    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        min_score: float = 0.1
    ) -> List[Tuple[dict, float]]:
        """
        Perform hybrid search combining semantic and keyword matching.
        
        Args:
            query: Search query text
            limit: Maximum number of results
            semantic_weight: Weight for semantic similarity (0-1)
            keyword_weight: Weight for keyword matching (0-1)
            min_score: Minimum combined score
            
        Returns:
            List of (tool_dict, combined_score) tuples
        """
        # Check if semantic search is disabled
        if os.environ.get('DISABLE_SEMANTIC_SEARCH', '').lower() == 'true':
            return self.keyword_search(query, limit)
        
        # Get results from both methods
        semantic_results = self.semantic_search(query, limit=limit * 2)
        keyword_results = self.keyword_search(query, limit=limit * 2)
        
        # Create score maps
        semantic_scores = {r[0]['id']: r[1] for r in semantic_results}
        keyword_scores = {r[0]['id']: r[1] for r in keyword_results}
        
        # Get all unique tool IDs
        all_tool_ids = set(semantic_scores.keys()) | set(keyword_scores.keys())
        
        # Calculate combined scores
        combined_scores = []
        for tool_id in all_tool_ids:
            sem_score = semantic_scores.get(tool_id, 0.0)
            kw_score = keyword_scores.get(tool_id, 0.0)
            
            combined = (sem_score * semantic_weight) + (kw_score * keyword_weight)
            
            if combined >= min_score:
                combined_scores.append((tool_id, combined, sem_score, kw_score))
        
        # Sort by combined score descending
        combined_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return top results
        results = []
        for tool_id, combined, sem, kw in combined_scores[:limit]:
            tool_data = self._tools_cache.get(tool_id)
            if tool_data:
                # Add score breakdown for debugging/display
                tool_data_with_scores = dict(tool_data)
                tool_data_with_scores['_semantic_score'] = round(sem, 3)
                tool_data_with_scores['_keyword_score'] = round(kw, 3)
                results.append((tool_data_with_scores, round(combined, 3)))
        
        return results
    
    def reindex_all_tools(self) -> int:
        """
        Regenerate embeddings for all tools in the database.
        
        Returns:
            Number of tools reindexed
        """
        from app import app
        from models import db, Tool
        
        count = 0
        with app.app_context():
            tools = Tool.query.all()
            
            for tool in tools:
                searchable_text = self._get_searchable_text(tool)
                embedding = self.generate_embedding(searchable_text)
                
                # Store embedding as JSON in the database
                tool.embedding = self.embedding_to_json(embedding)
                tool.embedding_text = searchable_text[:500]  # Store what was embedded
                
                # Update memory cache
                self._embeddings_cache[tool.id] = np.array(embedding)
                self._tools_cache[tool.id] = {
                    'id': tool.id,
                    'name': tool.name,
                    'description': tool.description,
                    'short_description': tool.short_description,
                    'category': tool.category,
                    'rating': tool.rating,
                    'review_count': tool.review_count,
                    'pricing': tool.pricing,
                    'website': tool.website,
                    'logo': tool.logo,
                    'tags': tool.tags,
                    'features': tool.features
                }
                
                count += 1
                if count % 10 == 0:
                    print(f"  Indexed {count} tools...")
            
            db.session.commit()
            self._cache_loaded = True
            
        print(f"✅ Reindexed {count} tools")
        return count
    
    def index_single_tool(self, tool) -> bool:
        """
        Generate and store embedding for a single tool.
        
        Args:
            tool: Tool model instance
            
        Returns:
            True if successful
        """
        try:
            searchable_text = self._get_searchable_text(tool)
            embedding = self.generate_embedding(searchable_text)
            
            tool.embedding = self.embedding_to_json(embedding)
            tool.embedding_text = searchable_text[:500]
            
            # Update memory cache
            self._embeddings_cache[tool.id] = np.array(embedding)
            self._tools_cache[tool.id] = {
                'id': tool.id,
                'name': tool.name,
                'description': tool.description,
                'short_description': tool.short_description,
                'category': tool.category,
                'rating': tool.rating,
                'review_count': tool.review_count,
                'pricing': tool.pricing,
                'website': tool.website,
                'logo': tool.logo,
                'tags': tool.tags,
                'features': tool.features
            }
            
            return True
        except Exception as e:
            print(f"❌ Failed to index tool {tool.id}: {e}")
            return False
    
    def clear_cache(self):
        """Clear the in-memory embedding cache"""
        self._embeddings_cache.clear()
        self._tools_cache.clear()
        self._cache_loaded = False
        print("🗑️ Embedding cache cleared")


# Convenience functions for direct use
def search_tools(query: str, limit: int = 10) -> List[Tuple[dict, float]]:
    """Convenience function for hybrid search"""
    engine = get_search_engine()
    return engine.hybrid_search(query, limit=limit)


def generate_tool_embedding(tool) -> str:
    """Generate embedding for a tool and return as JSON string"""
    engine = get_search_engine()
    engine.index_single_tool(tool)
    return tool.embedding
