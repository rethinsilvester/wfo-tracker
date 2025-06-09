import os
from flask import Flask, request, render_template, jsonify
import pandas as pd
from werkzeug.utils import secure_filename
import logging
from datetime import datetime

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def clean_employee_data(employees):
    """Clean and deduplicate employee data"""
    # Remove duplicates and filter out invalid entries
    seen_names = set()
    valid_employees = []
    
    for employee in employees:
        name = employee.get('name', '').strip()
        
        # Skip if name is empty, "Employee Name", or already seen
        if (not name or 
            name.lower() in ['employee name', 'name', ''] or 
            name in seen_names or
            name == 'nan'):
            continue
            
        # Skip if all attendance values are 0 (likely invalid row)
        total_attendance = (employee['summary'].get('WFO', 0) + 
                          employee['summary'].get('WFH', 0))
        
        if total_attendance == 0:
            continue
            
        seen_names.add(name)
        valid_employees.append(employee)
    
    logger.info(f"Cleaned data: {len(valid_employees)} valid employees from {len(employees)} total entries")
    return valid_employees

def process_excel_file(filepath):
    """Process Excel file and extract employee attendance data"""
    try:
        # Read all sheets
        excel_file = pd.ExcelFile(filepath)
        all_data = {}
        
        for sheet_name in excel_file.sheet_names:
            logger.info(f"Processing sheet: {sheet_name}")
            
            # Read the sheet - simplified approach
            df = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
            
            if df.empty or len(df) < 3:
                continue
                
            # Get the data as simple lists
            header_row = df.iloc[0].fillna('').astype(str).tolist()
            day_row = df.iloc[1].fillna('').astype(str).tolist()
            
            # Find date columns (starting from column 5)
            date_columns = []
            dates_info = []
            
            for i in range(5, len(header_row)):
                if header_row[i] and day_row[i] and header_row[i] != 'nan':
                    date_columns.append(i)
                    dates_info.append({
                        'index': i,
                        'date': header_row[i],
                        'day': day_row[i]
                    })
            
            # Process employee data
            employees = []
            for idx in range(2, len(df)):
                row = df.iloc[idx].fillna('').astype(str).tolist()
                
                if not row[0] or row[0] == 'nan':
                    continue
                
                employee = {
                    'name': row[0].strip(),
                    'person_id': row[1] if len(row) > 1 else '',
                    'department': row[2] if len(row) > 2 else '',
                    'team_manager': row[3] if len(row) > 3 else '',
                    'shift_timings': row[4] if len(row) > 4 else '',
                    'attendance': {},
                    'summary': {'WFO': 0, 'WFH': 0, 'SL': 0, 'PL': 0, 'Total_Days': 0}
                }
                
                # Process attendance for each date
                for date_idx, col_idx in enumerate(date_columns):
                    if col_idx < len(row) and row[col_idx] and row[col_idx] != 'nan':
                        status = str(row[col_idx]).strip().upper()
                        employee['attendance'][date_idx] = status
                        
                        # Count summary
                        if status in employee['summary']:
                            employee['summary'][status] += 1
                        
                        # Count total working days (excluding weekends)
                        if date_idx < len(dates_info):
                            day_of_week = dates_info[date_idx]['day']
                            if day_of_week.lower() not in ['saturday', 'sunday']:
                                employee['summary']['Total_Days'] += 1
                
                employees.append(employee)
            
            # Clean the employee data to remove duplicates and invalid entries
            cleaned_employees = clean_employee_data(employees)
            
            all_data[sheet_name] = {
                'employees': cleaned_employees,
                'dates': dates_info,
                'total_employees': len(cleaned_employees),
                'working_days': len([d for d in dates_info if d['day'].lower() not in ['saturday', 'sunday']])
            }
        
        return all_data
    
    except Exception as e:
        logger.error(f"Error processing Excel file: {str(e)}")
        raise e

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload Excel files only.'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Process the Excel file
        data = process_excel_file(filepath)
        
        # Clean up uploaded file
        os.remove(filepath)
        
        # Count total valid employees across all sheets
        total_employees = sum(len(sheet_data['employees']) for sheet_data in data.values())
        
        return jsonify({
            'success': True,
            'data': data,
            'message': f'File processed successfully. Found {total_employees} valid employees across {len(data)} sheets.'
        })
    
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': f'Error processing file: {str(e)}'}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    # Run with built-in Flask server for simplicity
    #app.run(host='0.0.0.0', port=5000, debug=True)
    if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
