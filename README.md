🌍 AQI Dashboard – AM30x Sensor (Flask)

A responsive web dashboard for monitoring Indoor Air Quality (AQI) using Milesight AM30x LoRaWAN sensors, built with Python Flask and SQLite.

This project visualizes real-time and historical environmental data such as PM2.5, PM10, CO₂, Temperature, Humidity, TVOC, and more, with support for multi-floor map UI, alarm management, and admin configuration.

✨ Features
📊 AQI Monitoring

Real-time AQI status: Good / Moderate / Unhealthy

Average Indoor & Outdoor values

Customizable AQI severity mapping (future-ready for Fire Alarm, Energy systems)

🗺️ Map UI (Floor Plan)

Upload floor plan images

Multi-floor support with auto-rotation

Drag & drop sensor positions

Sensor icons reflect real-time severity

📈 Data Visualization

Daily graph (24-hour timeline)

Weekly overview graph

Full-screen graph view with date range & sampling selector

🚨 Alarm & Notification

Real-time alarm count (bell icon)

Daily alarm summary (calendar icon)

Alert banner for critical alarms

Full alarm history page

⚙️ Admin Settings

Project name & location

AQI severity color/label mapping

Floor plan & sensor icon management

Auto-rotate floor interval

Role-based access (Admin only)

📥 Data Export

Export sensor data to CSV with one click

🧠 Supported Sensor (Milesight AM30x)

The system is designed specifically for Milesight AM30x Indoor Ambience Sensors.

Supported metrics:

Temperature (°C)

Humidity (%RH)

CO₂ (ppm)

PM2.5 / PM10 (µg/m³)

TVOC (IAQ / mg/m³)

Light (Lux)

Barometric Pressure (hPa)

Motion (Occupied / Vacant)

Signal Quality (%)

🏗️ Tech Stack
Layer	Technology
Backend	Python Flask
Template	Jinja2
Database	SQLite
Frontend	HTML, CSS, JS
UI Framework	Bootstrap 5
Charts	Chart.js
Auth	Session-based
🗂️ Project Structure
aqi-dashboard/
│
├── app.py
├── requirements.txt
├── settings.json
│
├── db/
│   ├── sensordata.db
│   ├── calendar.db
│   └── alarm.db
│
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── settings.html
│   ├── alarms.html
│   └── graphs/
│
├── static/
│   ├── css/
│   ├── js/
│   └── icons/
│
└── services/
    ├── db_service.py
    ├── alarm_service.py
    └── graph_service.py

🗄️ Database Overview
sensordata.db

devices

sensor_readings

alarm_events

calendar.db

daily_alarm_summary
(generated automatically at 23:50 each day)

alarm.db

alarm_history

🚀 Getting Started
1️⃣ Clone Repository
git clone https://github.com/your-org/aqi-dashboard.git
cd aqi-dashboard

2️⃣ Install Dependencies
pip install -r requirements.txt

3️⃣ Run Application
flask --app app run


Open browser:

http://127.0.0.1:5000

🔐 Authentication

Admin-only access for Settings

Credentials configurable via environment variables or settings.json

📤 CSV Export

Click the Download icon on the top-right corner to export sensor data:

/export/sensor.csv

🧩 Extensibility

This system is designed to be modular and extensible:

Add Energy & Carbon module

Integrate Fire Alarm system

Connect to Milesight IoT Cloud / LoRaWAN uplink

Convert to REST API + SPA frontend

📌 Roadmap

 Energy & Carbon dashboard

 Waste management module

 Role-based user management

 Real-time WebSocket updates

 LoRaWAN payload decoder

📄 License

MIT License © 2025
Use freely for commercial and non-commercial projects.

🤝 Contribution

Pull requests are welcome.
For major changes, please open an issue first to discuss what you would like to change.

📬 Contact

For support or customization, please contact the project maintainer.
