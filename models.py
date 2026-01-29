from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=True)  # Made nullable for OAuth users
    google_id = db.Column(db.String(50), unique=True, nullable=True)  # Google OAuth ID
    avatar = db.Column(db.String(20), default='👤')
    points = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    badges = db.Column(db.Text, default='[]')  # JSON string
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Email verification fields
    email_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(255), nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    
    # Password reset fields
    reset_token = db.Column(db.String(255), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    
    def get_badges(self):
        return json.loads(self.badges)
    
    def add_badge(self, badge):
        badges = self.get_badges()
        if badge not in badges:
            badges.append(badge)
            self.badges = json.dumps(badges)
    
    def add_points(self, points):
        """Add points and recalculate level"""
        self.points += points
        self.level = self.calculate_level()
    
    def calculate_level(self):
        """Calculate level based on points (every 100 points = 1 level)"""
        return max(1, (self.points // 100) + 1)
    
    def get_saved_tools(self):
        """Get all tools bookmarked by this user"""
        return [bookmark.tool for bookmark in self.tool_bookmarks]
    
    def get_saved_prompts(self):
        """Get all prompts bookmarked by this user"""
        return [bookmark.prompt for bookmark in self.prompt_bookmarks]
    
    def get_followed_categories(self):
        """Get all categories followed by this user"""
        return [follow.category for follow in self.followed_categories]

class Tool(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    short_description = db.Column(db.String(200), nullable=False)
    logo = db.Column(db.String(10), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # Keep for backward compatibility
    rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    pricing = db.Column(db.String(20), nullable=False)
    website = db.Column(db.String(200), nullable=False)
    features = db.Column(db.Text, default='[]')  # JSON string
    integrations = db.Column(db.Text, default='[]')  # JSON string
    tags = db.Column(db.Text, default='[]')  # JSON string
    
    # Semantic search embedding columns
    embedding = db.Column(db.Text, nullable=True)  # JSON-encoded embedding vector
    embedding_text = db.Column(db.Text, nullable=True)  # Source text that was embedded
    
    def get_searchable_text(self) -> str:
        """Generate searchable text for embedding from all relevant fields"""
        parts = []
        
        if self.name:
            parts.append(self.name)
        if self.short_description:
            parts.append(self.short_description)
        if self.description:
            parts.append(self.description[:500])  # Limit description length
        if self.category:
            parts.append(f"Category: {self.category}")
        
        # Parse tags if stored as JSON
        if self.tags:
            try:
                if self.tags.startswith('['):
                    tags = json.loads(self.tags)
                else:
                    tags = [t.strip() for t in self.tags.split(',')]
                parts.append(f"Tags: {', '.join(tags)}")
            except:
                parts.append(f"Tags: {self.tags}")
        
        return ' '.join(parts)
    
    def get_all_categories(self):
        """Get all categories this tool belongs to"""
        categories = [rel.category_name for rel in self.category_relationships]
        
        # Also parse the main category field for backward compatibility
        if self.category:
            if ' & ' in self.category:
                # Split merged categories
                merged_cats = [cat.strip() for cat in self.category.split(' & ')]
                categories.extend(merged_cats)
            else:
                categories.append(self.category)
        
        # Remove duplicates and sort
        return sorted(list(set(categories)))
    
    def get_merged_category_string(self):
        """Get a merged category string for display (e.g., 'Design & Image Generation')"""
        categories = self.get_all_categories()
        if len(categories) <= 1:
            return categories[0] if categories else 'Uncategorized'
        return ' & '.join(categories)
    
    def add_category(self, category_name):
        """Add a new category to this tool"""
        if not category_name:
            return
        
        # Check if category already exists
        existing = ToolCategory.query.filter_by(
            tool_id=self.id, 
            category_name=category_name
        ).first()
        
        if not existing:
            new_category = ToolCategory(
                tool_id=self.id,
                category_name=category_name
            )
            db.session.add(new_category)
            
            # Also update the main category field for backward compatibility
            if not self.category:
                self.category = category_name
            elif self.category != category_name:
                # Merge categories in the main field, avoiding duplicates
                current_categories = self.get_all_categories()
                if category_name not in current_categories:
                    # Clean up the main category field to avoid duplication
                    if ' & ' in self.category:
                        # Split existing categories and add new one
                        existing_cats = [cat.strip() for cat in self.category.split(' & ')]
                        if category_name not in existing_cats:
                            existing_cats.append(category_name)
                            self.category = ' & '.join(sorted(existing_cats))
                    else:
                        # Simple case: just add the new category
                        self.category = f"{self.category} & {category_name}"

class Prompt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    tool = db.Column(db.String(100), nullable=False)
    tool_id = db.Column(db.Integer, db.ForeignKey('tool.id'), nullable=True)
    tool_website = db.Column(db.String(500), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref='prompts')
    tool_relationship = db.relationship('Tool', backref='prompts')
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    tags = db.Column(db.Text, default='[]')  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref='posts')
    type = db.Column(db.String(20), default='post', nullable=False)
    upvotes = db.Column(db.Integer, default=0)
    comments = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    tags = db.Column(db.Text, default='[]')  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(10), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    tool_count = db.Column(db.Integer, default=0)

# New models for user actions

class ToolCategory(db.Model):
    """Many-to-many relationship between tools and categories"""
    id = db.Column(db.Integer, primary_key=True)
    tool_id = db.Column(db.Integer, db.ForeignKey('tool.id', ondelete='CASCADE'), nullable=False)
    category_name = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tool = db.relationship('Tool', backref='category_relationships')
    
    # Ensure unique tool-category combinations
    __table_args__ = (db.UniqueConstraint('tool_id', 'category_name', name='unique_tool_category'),)

class ToolBookmark(db.Model):
    """User bookmarks for tools"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tool_id = db.Column(db.Integer, db.ForeignKey('tool.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='tool_bookmarks')
    tool = db.relationship('Tool', backref='bookmarks')

class PromptBookmark(db.Model):
    """User bookmarks for prompts"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prompt_id = db.Column(db.Integer, db.ForeignKey('prompt.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='prompt_bookmarks')
    prompt = db.relationship('Prompt', backref='bookmarks')

class ToolVote(db.Model):
    """User votes on tools"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tool_id = db.Column(db.Integer, db.ForeignKey('tool.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)  # 'upvote' or 'downvote'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='tool_votes')
    tool = db.relationship('Tool', backref='votes')

class PromptVote(db.Model):
    """User votes on prompts"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prompt_id = db.Column(db.Integer, db.ForeignKey('prompt.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)  # 'upvote' or 'downvote'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='prompt_votes')
    prompt = db.relationship('Prompt', backref='votes')

class PostVote(db.Model):
    """User votes on posts"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)  # 'upvote' or 'downvote'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='post_votes')
    post = db.relationship('Post', backref='votes')

class FollowedCategory(db.Model):
    """Categories that users follow"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='followed_categories')
    category = db.relationship('Category', backref='followers')

class UserActivity(db.Model):
    """Track user activities for points and badges"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # 'bookmark_tool', 'vote_prompt', etc.
    points_earned = db.Column(db.Integer, default=0)
    description = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='activities')

class UserNotification(db.Model):
    """User notifications"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)  # 'upvote', 'badge', 'new_tool', etc.
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='notifications')

class PromptLike(db.Model):
    """User likes for prompts"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prompt_id = db.Column(db.Integer, db.ForeignKey('prompt.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='prompt_likes')
    prompt = db.relationship('Prompt', backref='likes_relationship')
    
    # Ensure a user can only like a prompt once
    __table_args__ = (db.UniqueConstraint('user_id', 'prompt_id', name='unique_prompt_like'),)

class PostLike(db.Model):
    """User likes for posts"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='post_likes')
    post = db.relationship('Post', backref='likes_relationship')
    
    # Ensure a user can only like a post once
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_post_like'),)

class ToolReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tool_id = db.Column(db.Integer, db.ForeignKey('tool.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='tool_reviews')
    tool = db.relationship('Tool', backref='reviews')

    # One review per user per tool
    __table_args__ = (db.UniqueConstraint('user_id', 'tool_id', name='unique_tool_review'),)

class PostComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('post_comment.id'), nullable=True)  # For replies
    content = db.Column(db.Text, nullable=False)
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='post_comments')
    post = db.relationship('Post', backref='comments_relationship')
    
    # Self-referential relationship for replies
    parent_comment = db.relationship('PostComment', remote_side=[id], backref='replies')

class CommentLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment_id = db.Column(db.Integer, db.ForeignKey('post_comment.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='comment_likes')
    comment = db.relationship('PostComment', backref='likes_relationship')

    # One like per user per comment
    __table_args__ = (db.UniqueConstraint('user_id', 'comment_id', name='unique_comment_like'),)