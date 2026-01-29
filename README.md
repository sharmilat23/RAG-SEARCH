# AnySite Hub

A feature-rich Flask web application for sharing, reviewing, and discovering AI tools, prompts, and posts.

## 🚀 Features

*   **User Authentication**: Secure signup/login with email verification and password reset.
*   **OAuth Integration**: Sign in with Google.
*   **Community Features**: 
    *   Voting system (Upvotes/Downvotes) for tools, prompts, and posts.
    *   Comments and replies.
    *   User profiles with levels, badges, and activity tracking.
*   **Content Management**:
    *   AI Tools directory with categories, ratings, and reviews.
    *   Prompt library with tagging.
    *   Community posts.
*   **Performance**:
    *   Rate limiting (Flask-Limiter).
    *   Response compression (Flask-Compress).
    *   Database connection pooling.
*   **SEO Optimized**: Dynamic sitemap, meta tags, and robots.txt generation.

## 🛠️ Tech Stack

*   **Backend**: Python, Flask
*   **Database**: SQLAlchemy (SQLite for dev, PostgreSQL supported for prod)
*   **Templates**: Jinja2 (Serverside Rendering)
*   **Styling**: HTML/CSS (Static assets)
*   **Other**: Redis (optional, for rate limiting)

## 📋 Prerequisites

*   Python 3.10+
*   pip
*   (Optional) Redis server

## ⚡ Installation

1.  **Clone the repository**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create and activate a virtual environment**
    ```bash
    # Windows
    python -m venv venv
    venv\Scripts\activate

    # macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuration

Create a `.env` file in the root directory and configure the following variables:

```ini
# Core Secrets
SECRET_KEY=change-this-to-a-secure-random-string

# Database (Defaults to SQLite if not set)
# DATABASE_URL=postgresql://user:password@localhost/dbname

# OAuth (Google)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email / SMTP (For verification & resets)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-email@example.com
SMTP_PASSWORD=your-email-password
MAIL_SENDER=no-reply@yourdomain.com
EMAIL_VERIFY_SALT=unique-salt-string

# Rate Limiting (Optional - defaults to memory)
# RATELIMIT_STORAGE_URI=redis://localhost:6379/0
```

## 🏃‍♂️ Running the App

**Development Mode:**

```bash
flask run --debug
```

The application will be available at `http://localhost:5000`.

**Production:**

It is recommended to use Gunicorn (included in requirements):

```bash
gunicorn -w 4 -k gevent app:app
```

## 🐳 Docker

A `Dockerfile` is included for containerized deployment.

```bash
# Build the image
docker build -t anysite-hub .

# Run the container
docker run -p 5000:5000 --env-file .env anysite-hub
```



# AI Tools Hub - Flask Application

A comprehensive AI tools discovery and community platform built with Flask, featuring personalized recommendations, user-generated content, and gamification elements.

## 🚀 Features Implemented

### Core Functionality
- **AI Tools Directory**: Browse and discover AI tools by category, pricing, and features
- **AI Agent Assistant**: Get personalized tool recommendations through conversational interface
- **Prompts Library**: Share, test, and discover AI prompts with user upload functionality
- **Community Platform**: Discussion threads, Q&A, and user-generated content
- **User Dashboard**: Personalized recommendations, saved items, and activity tracking

### Enhanced User Experience
- **Typeahead Search**: Real-time search suggestions with auto-complete
- **Auto-updated Carousels**: Dynamic trending tools showcase
- **Advanced Filtering**: Filter by category, pricing, API availability, integrations, and features
- **Grid/List View Toggle**: Flexible viewing options for tools and prompts
- **Bookmark/Save System**: Save favorite tools and prompts for later
- **Test Prompt Interface**: Built-in prompt testing with simulated AI responses

### Gamification & Engagement
- **Points System**: Earn points for contributions and engagement
- **Badges & Achievements**: Unlock badges for various activities
- **Leaderboards**: Community rankings and competitive elements
- **Voting System**: Upvote/downvote tools, prompts, and posts
- **Progress Tracking**: Level progression and activity history

### Personalization
- **Smart Recommendations**: AI-powered tool suggestions based on user behavior
- **Followed Categories**: Personalized content based on interests
- **Recent Activity**: Track user engagement and contributions
- **Saved Items**: Quick access to bookmarked tools and prompts
- **Notifications**: Real-time updates on community activity

### Business Model UI Hooks
- **Premium Features**: UI elements for future subscription tiers
- **Affiliate Links**: Tool website integration for monetization
- **Sponsored Content**: Placeholder sections for promoted tools
- **Newsletter Signup**: Email collection for marketing campaigns

## 🛠️ Technology Stack

### Backend
- **Flask 2.3.3**: Web framework
- **SQLAlchemy 2.0.21**: ORM for database management
- **Flask-Login 0.6.3**: User authentication
- **SQLite**: Database (development)

### Frontend
- **Jinja2**: Template engine
- **Tailwind CSS**: Utility-first CSS framework
- **JavaScript**: Interactive features and AJAX calls
- **SVG Icons**: Scalable vector graphics for UI elements

### Key Libraries
- **Werkzeug 2.3.7**: WSGI utilities
- **MarkupSafe 2.1.3**: Safe HTML/XML markup
- **itsdangerous 2.1.2**: Cryptographic signing
- **click 8.1.7**: Command line interface
- **blinker 1.6.3**: Fast dispatching

## 📦 Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd anysite_hub
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   
   # On Windows
   venv\Scripts\activate
   
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize database**
   ```bash
   python sample_data.py
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

6. **Access the application**
   Open your browser and navigate to `http://localhost:5000`

## 🗂️ Project Structure

```
anysite_hub/
├── app.py                 # Main Flask application
├── models.py             # SQLAlchemy database models
├── sample_data.py        # Database seeding script
├── requirements.txt      # Python dependencies
├── README.md            # Project documentation
└── templates/           # Jinja2 HTML templates
    ├── base.html        # Base template with navigation
    ├── home.html        # Homepage with hero section
    ├── categories.html  # Tools directory with filters
    ├── tool_detail.html # Individual tool pages
    ├── ai_agent.html    # AI assistant interface
    ├── prompts.html     # Prompts library
    ├── community.html   # Community discussions
    ├── dashboard.html   # User dashboard
    └── login.html       # Authentication page
```

## 🎯 Key Features Breakdown

### 1. Homepage (`/`)
- **Hero Section**: Compelling headline with search functionality
- **Typeahead Search**: Real-time suggestions as you type
- **Auto-updated Carousel**: Trending tools showcase
- **Quick Categories**: Easy navigation to tool categories
- **Featured Content**: Prompts and community posts preview
- **Newsletter Signup**: Email collection for marketing

### 2. Categories Page (`/categories`)
- **Advanced Filters**: Category, pricing, API availability, integrations
- **Grid/List View**: Toggle between different viewing modes
- **Save Search**: Bookmark filter combinations
- **Load More**: Pagination for large tool collections
- **Tool Cards**: Rich information display with ratings and features

### 3. AI Agent (`/agent`)
- **Conversational Interface**: Chat-based tool recommendations
- **Personalized Suggestions**: Based on user preferences
- **Quick Prompts**: Pre-defined conversation starters
- **Sidebar Features**: Popular categories and recent searches
- **Real-time Responses**: Dynamic tool recommendations

### 4. Prompts Library (`/prompts`)
- **User Upload**: Submit new prompts with form validation
- **Test Interface**: Built-in prompt testing functionality
- **Voting System**: Upvote/downvote prompts
- **Advanced Filtering**: Search by tool, category, difficulty
- **Gamification**: Points for contributions and engagement

### 5. Community (`/community`)
- **Discussion Threads**: Deep conversations about AI tools
- **Q&A Section**: Question and answer format
- **Leaderboards**: Community rankings and achievements
- **Badges System**: Recognition for contributions
- **Trending Topics**: Popular discussion themes

### 6. User Dashboard (`/dashboard`)
- **Personalized Recommendations**: AI-powered tool suggestions
- **Saved Items**: Quick access to bookmarked content
- **Activity Tracking**: Recent contributions and engagement
- **Progress Stats**: Points, levels, and achievements
- **Quick Actions**: Fast access to common tasks

## 🔧 API Endpoints

### Authentication
- `GET /login` - Login page
- `GET /logout` - Logout and redirect

### Core Pages
- `GET /` - Homepage
- `GET /categories` - Tools directory
- `GET /tool/<id>` - Individual tool page
- `GET /agent` - AI assistant
- `GET /prompts` - Prompts library
- `GET /community` - Community discussions
- `GET /dashboard` - User dashboard

### API Endpoints
- `POST /api/agent/chat` - AI agent responses
- `POST /api/bookmark/tool/<id>` - Bookmark tools
- `POST /api/bookmark/prompt/<id>` - Bookmark prompts
- `POST /api/vote/post/<id>` - Vote on posts
- `POST /api/vote/prompt/<id>` - Vote on prompts
- `GET /api/recommendations` - Personalized recommendations
- `GET /api/leaderboard` - Community rankings
- `GET /api/notifications` - User notifications
- `GET /api/search/suggestions` - Search suggestions
- `POST /api/test/prompt` - Test prompts
- `POST /api/upload/prompt` - Upload new prompts
- `POST /api/upload/post` - Create community posts
- `GET /api/user/stats` - User statistics
- `GET /api/user/followed-categories` - Followed categories
- `GET /api/user/saved-items` - Saved items

## 🎨 UI/UX Features

### Design System
- **Consistent Color Scheme**: Blue and purple gradients throughout
- **Responsive Design**: Mobile-first approach with Tailwind CSS
- **Modern Icons**: SVG icons for better scalability
- **Smooth Animations**: Hover effects and transitions
- **Accessibility**: Proper ARIA labels and keyboard navigation

### Interactive Elements
- **Modal Dialogs**: Upload forms and test interfaces
- **Toast Notifications**: Success/error feedback
- **Loading States**: Visual feedback during operations
- **Infinite Scroll**: Smooth pagination experience
- **Real-time Updates**: Dynamic content without page refresh

## 🚀 Future Enhancements

### Planned Features
- **Real AI Integration**: Connect to actual AI APIs for prompt testing
- **User Authentication**: Complete login/logout system
- **Database Integration**: Persistent data storage
- **Email Notifications**: Automated email campaigns
- **Analytics Dashboard**: User behavior tracking
- **Mobile App**: Native mobile application
- **API Documentation**: Comprehensive API docs
- **Admin Panel**: Content management system

### Business Features
- **Subscription Tiers**: Premium features and content
- **Affiliate Marketing**: Commission-based tool recommendations
- **Sponsored Content**: Promoted tools and features
- **Email Marketing**: Newsletter and promotional campaigns
- **Analytics**: User behavior and conversion tracking

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue in the GitHub repository
- Contact the development team
- Check the documentation for common solutions

## 🙏 Acknowledgments

- Flask community for the excellent web framework
- Tailwind CSS for the utility-first CSS framework
- All contributors who helped build this platform
- The AI tools community for inspiration and feedback

---

**AI Tools Hub** - Discover, share, and master AI tools for every task! 🚀
