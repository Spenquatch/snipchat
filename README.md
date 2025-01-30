# SnipChat

A lightweight system tray application that captures screenshots and analyzes them using GPT-4 Vision API.

## Features

- System tray integration
- Screenshot capture with Ctrl + Shift + S
- GPT-4 Vision API integration for image analysis
- Notepad-style interface for viewing responses
- Persistent storage of responses

## Setup Instructions

1. Install Python 3.8 or higher if not already installed.

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your OpenAI API key:
   - Create a `.env` file in the project directory
   - Add your OpenAI API key: `OPENAI_API_KEY=your_api_key_here`

4. Run the application:
```bash
python main.py
```

## Usage

- The app runs in the system tray (look for the icon in your taskbar)
- Press Ctrl + Shift + S to capture a screenshot
- Right-click the tray icon to:
  - Open the notepad view
  - Exit the application
- The notepad view shows all GPT-4 Vision API responses
- Responses are automatically saved for future sessions

## Requirements

- Windows 10 or higher
- Python 3.8+
- OpenAI API key with GPT-4 Vision access 