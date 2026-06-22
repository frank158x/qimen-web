# qimen-web
奇门遁甲排盘，可在Codespaces里直接使用。
打开Codespaces后，在终端输入

./start.sh

排盘之时，心中所想所求之事，虔诚提问。

一事不再占。
连两次占，影响大吗？
对你未来的实际盈利缘分没有任何影响，但对你接下来的判断力有影响。


A modern web application for generating and interpreting Qimen Dunjia charts.


<img width="2864" height="1468" alt="首页截图" src="https://github.com/user-attachments/assets/7e818e5b-810d-4782-8beb-c17d57908e1e" />


## Features

✔ Qimen chart generation

✔ Solar/Lunar calendar conversion

✔ Astronomical time correction

✔ Historical records

✔ AI-assisted interpretation

## Tech Stack

Python
Flask
SQLite
HTML/CSS
JavaScript
LunarPython

## Screenshots

<img width="2864" height="1468" alt="首页截图" src="https://github.com/user-attachments/assets/d8c06672-b897-4cc9-8a64-33e3b02b69fe" />
<img width="1387" height="1465" alt="jiedu" src="https://github.com/user-attachments/assets/40e0cbf0-e588-46ca-acbd-8a4cba644dbe" />


## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/frank158x/qimen-web.git
cd qimen-web
```

### 2. Create a virtual environment (Recommended)

```bash
python -m venv venv
```

Windows

```bash
venv\Scripts\activate
```

Linux / macOS

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure AI API (Optional)

The project supports AI-assisted chart interpretation.

Create a `.env` file (or update the configuration file) and add your API credentials:

```text
API_KEY=your_api_key
BASE_URL=your_api_endpoint
MODEL=your_model_name
```

> **Note:** The core Qimen Dunjia chart generation works independently. AI is only used for natural language interpretation.

### 5. Start the application

```bash
python app.py
```

Open your browser and visit:

```
http://127.0.0.1:5000
```

## Roadmap

□ User API configuration

□ Multi-model support

□ Better UI

□ Docker

□ Mobile adaptation

