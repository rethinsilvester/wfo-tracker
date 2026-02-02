# WMS/UV Admin WFO Tracker

A simple, modern work-from-office attendance tracker for your team.

![Dashboard Preview](preview.png)

## Features

- 🎨 Modern, fluidic gradient UI
- 📊 Team summary with WFO percentage
- 👤 Individual admin calendar view
- 📅 Monthly attendance breakdown
- 🎯 WFO target tracking (default: 70%)

## Quick Start

### Using Docker (Recommended)

```bash
docker-compose up -d
```

### Using Python directly

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`

## Excel File Format

Place your Excel file in the `data/` folder. The file should match the pattern `App_Admin_UV-WCS*.xlsx` (or any `.xlsx` file will work).

### Expected Sheet Structure

Each sheet represents a month (e.g., "January", "Feb 2025"):

| Employee Name | Person ID | Department | Team Manager | Shift | Day 1 | Day 2 | Day 3 | ... |
|--------------|-----------|------------|--------------|-------|-------|-------|-------|-----|
| John Doe     | 12345     | WMS        | Jane Smith   | 9-6   | WFO   | WFH   | WFO   | ... |
| Jane Smith   | 12346     | UV Admin   | Mike Brown   | 9-6   | WFO   | WFO   | Leave | ... |

### Supported Status Values

- `WFO` - Work From Office
- `WFH` - Work From Home
- `SL` or `Sick Leave` - Sick Leave
- `Leave` or `PL` or `Planned Leave` - Planned Leave
- `Holiday` or `India Holiday` - Holiday

## Daily Workflow

1. Update your Excel file with attendance data
2. Push to GitHub
3. The app automatically picks up the latest file from `data/` folder

## Configuration

Edit `app.py` to customize:

```python
CONFIG = {
    'team_name': 'WMS/UV Admin',
    'excel_pattern': 'App_Admin_UV-WCS*.xlsx',
    'data_folder': 'data',
    'wfo_target': 70  # Adjust target percentage
}
```

## File Structure

```
wfo_tracker/
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
├── Dockerfile
├── docker-compose.yml
├── data/               # Place Excel files here
│   └── App_Admin_UV-WCS_2025.xlsx
└── templates/
    ├── index.html      # Dashboard
    ├── calendar.html   # Admin detail view
    ├── no_data.html
    └── not_found.html
```

## API Endpoints

- `GET /` - Dashboard with team summary
- `GET /admin/<name>` - Calendar view for specific admin
- `GET /api/refresh` - Check data status
- `GET /health` - Health check

## License

MIT
