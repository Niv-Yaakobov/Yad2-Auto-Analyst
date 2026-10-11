# Yad2 Auto-Analyst & Deal Hunter 🚗🤖

An end-to-end automated pipeline for discovering, filtering, and evaluating used car listings from Yad2. The system extracts listing data while bypassing bot protections, evaluates deal value and mechanical reliability using AI (Google Gemini API), actively monitors price drops, and presents everything on a modern web dashboard alongside real-time email alerts.

## ✨ Key Features

* **Smart Scraping:** Utilizes `curl_cffi` to impersonate real browser TLS fingerprints and bypass anti-bot protections (e.g., PerimeterX). Extracts complete ad details, including hidden original prices.
* **AI Evaluation:** Performs an isolated, individual assessment for each vehicle based on mechanical reliability, maintenance costs, ownership history, and pricing. Automatically filters out vehicles scoring below 7.0/10.
* **Price Drop Monitor:** A dedicated secondary script that tracks saved vehicles, detects price reductions, triggers a re-evaluation via Gemini, and automatically purges deleted or sold listings from the database.
* **Push Email Alerts:** Sends formatted HTML emails when top-tier deals are discovered (score > 8.5) or when sellers drop their prices.
* **Interactive Dashboard:** A responsive Frontend (HTML5/CSS3/Vanilla JS) for filtering and sorting recommendations, featuring visual badges and strikethrough metrics for discounted cars.
* **State Management & Recovery:** Maintains an automated memory state (`processed_tokens.json`) to prevent duplicate API calls, alongside a local backup mechanism (`scraped_cars.json`) to recover seamlessly from API outages.

## 🏗️ System Architecture

The project consists of three core components designed to run on separate schedules (via Cron Jobs or GitHub Actions):

1. **`main.py` (Discovery & Evaluation):**
   Scans the main feed, filters out previously processed tokens, scrapes full details for new listings, analyzes them with Gemini, and saves the top recommendations.
2. **`price_monitor.py` (Price & Availability Tracker):**
   Iterates exclusively over existing recommendations in the database, checks if listings are still active, detects price drops, and re-evaluates updated deals.
3. **`index.html` (Web Dashboard):**
   Reads the static `gemini_results_history.json` file and renders an interactive UI for the user.

## 🚀 Getting Started

### 1. Prerequisites
* Python 3.9+
* Google Gemini API Key
* Gmail account with an **App Password** enabled (for SMTP email alerts)

### 2. Installation
```bash
git clone https://github.com/your-username/yad2-auto-analyst.git
cd yad2-auto-analyst
pip install -r requirements.txt
```

### 3. Environment Variables (`.env`)
Create a `.env` file in the root directory of the project and configure the following variables:
```env
GEMINI_API_KEY=your_gemini_api_key_here
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_RECEIVER=your_email@gmail.com
```

### 4. Usage
To run the main discovery and evaluation pipeline:
```bash
python main.py
```

To run the price drop and availability monitor on saved cars:
```bash
python price_monitor.py
```

## 📂 State & Data Files

The system automatically generates and maintains the following JSON files:
* `gemini_results_history.json`: The primary database containing all recommended vehicles, AI evaluations, additional metadata, and price drop alerts. Consumed by the frontend dashboard.
* `processed_tokens.json`: A persistent state file storing unique ad tokens that have already been evaluated, preventing duplicate processing and saving API quota.
* `scraped_cars.json`: A temporary recovery file created right before calling the Gemini API and automatically deleted upon a successful run.

> ⚠️ **Deployment Note (GitHub Actions / Cloud):** 
> Because the system relies on local JSON files for state persistence, running these scripts in stateless CI/CD environments (like GitHub Actions) requires configuring your workflow to `git commit` and `git push` the updated JSON files back to the repository at the end of each run, or syncing them with cloud object storage (such as AWS S3).

## 🛠️ Tech Stack
* **Python** – Core logic, scraping, and automation
* **curl_cffi** – Anti-bot web scraping & TLS fingerprinting
* **Google GenAI SDK** – AI evaluation (`gemini-3.5-flash`)
* **HTML5 / CSS3 / Vanilla JS** – Responsive frontend dashboard
* **Lucide Icons** – UI iconography

## ⚖️ Disclaimer
This project was created for educational and personal automation purposes. Scraping data from websites is subject to their respective Terms of Service. Always use reasonable delays between network requests to avoid overloading target servers.