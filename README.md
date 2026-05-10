# YouTube Assistant

This is an automated YouTube video production tool. It automates tasks like generating images using Google ImageFX and handling text-to-speech audio using Fish Audio.

## Features
- **Image Generation Automation:** Interacts with Google ImageFX to generate images automatically.
- **Audio Generation:** Integrates with Fish Audio API for text-to-speech tasks.
- **Flask Web Interface:** Provides an easy-to-use web UI to control the generation tasks and review the results.

## Requirements
- Python 3
- Playwright
- Flask
- Fish Audio SDK

## Setup
1. Clone this repository.
2. Install dependencies: `pip install -r requirements.txt`
3. Setup playwright: `playwright install`
4. Set up your `.env` file with any required API keys and credentials.
5. Run the server: `python server.py`
