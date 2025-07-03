import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
import io
import base64
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Configuration
UPLOAD_FOLDER = 'uploads'
MASTER_DATA_FOLDER = 'master_data'
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MASTER_DATA_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_master_data():
    """Load the latest master data if available"""
    master_file_path = os.path.join(MASTER_DATA_FOLDER, 'master_data.xlsx')
    metadata_path = os.path.join(MASTER_DATA_FOLDER, 'metadata.json')
    
    if os.path.exists(master_file_path):
        try:
            df = pd.read_excel(master_file_path)
            
            # Load metadata if exists
            metadata = {}
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
            
            return df, metadata
        except Exception as e:
            print(f"Error loading master data: {e}")
    
    return None, {}

def save_master_data(df, filename):
    """Save data as the new master data"""
    master_file_path = os.path.join(MASTER_DATA_FOLDER, 'master_data.xlsx')
    metadata_path = os.path.join(MASTER_DATA_FOLDER, 'metadata.json')
    
    try:
        # Save the Excel file
        df.to_excel(master_file_path, index=False)
        
        # Save metadata
        metadata = {
            'original_filename': filename,
            'upload_timestamp': datetime.now().isoformat(),
            'row_count': len(df),
            'column_count': len(df.columns),
            'columns': list(df.columns)
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return True
    except Exception as e:
        print(f"Error saving master data: {e}")
        return False

def create_visualizations(df):
    """Create visualizations from the dataframe"""
    plots = []
    
    try:
        # Set style
        plt.style.use('default')
        sns.set_palette("husl")
        
        # Get numeric columns
        numeric_columns = df.select_dtypes(include=['number']).columns.tolist()
        
        if len(numeric_columns) >= 2:
            # Correlation heatmap
            fig, ax = plt.subplots(figsize=(10, 8))
            correlation_matrix = df[numeric_columns].corr()
            sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', center=0, ax=ax)
            ax.set_title('Correlation Matrix of Numeric Variables')
            
            img = io.BytesIO()
            plt.savefig(img, format='png', bbox_inches='tight', dpi=300)
            img.seek(0)
            plot_url = base64.b64encode(img.getvalue()).decode()
            plots.append(('Correlation Matrix', plot_url))
            plt.close()
        
        # Distribution plots for first few numeric columns
        for i, col in enumerate(numeric_columns[:3]):
            if df[col].notna().sum() > 0:
                fig, ax = plt.subplots(figsize=(10, 6))
                df[col].hist(bins=30, alpha=0.7, ax=ax)
                ax.set_title(f'Distribution of {col}')
                ax.set_xlabel(col)
                ax.set_ylabel('Frequency')
                
                img = io.BytesIO()
                plt.savefig(img, format='png', bbox_inches='tight', dpi=300)
                img.seek(0)
                plot_url = base64.b64encode(img.getvalue()).decode()
                plots.append((f'Distribution: {col}', plot_url))
                plt.close()
        
        # If there are categorical columns, create a bar chart
        categorical_columns = df.select_dtypes(include=['object']).columns.tolist()
        for col in categorical_columns[:2]:  # First 2 categorical columns
            if df[col].notna().sum() > 0:
                value_counts = df[col].value_counts().head(10)  # Top 10 values
                if len(value_counts) > 1:
                    fig, ax = plt.subplots(figsize=(12, 6))
                    value_counts.plot(kind='bar', ax=ax)
                    ax.set_title(f'Top Values in {col}')
                    ax.set_xlabel(col)
                    ax.set_ylabel('Count')
                    plt.xticks(rotation=45, ha='right')
                    
                    img = io.BytesIO()
                    plt.savefig(img, format='png', bbox_inches='tight', dpi=300)
                    img.seek(0)
                    plot_url = base64.b64encode(img.getvalue()).decode()
                    plots.append((f'Top Values: {col}', plot_url))
                    plt.close()
        
    except Exception as e:
        print(f"Error creating visualization: {e}")
    
    return plots

@app.route('/')
def index():
    """Main page - show master data if available, otherwise show upload form"""
    df, metadata = load_master_data()
    
    if df is not None:
        # Show the existing data
        plots = create_visualizations(df)
        
        return render_template('results.html', 
                             tables=[df.head(100).to_html(classes='data table table-striped', 
                                                          table_id='dataTable')],
                             titles=['Latest Data'],
                             plots=plots,
                             metadata=metadata,
                             show_upload_new=True)  # Flag to show "Upload New Data" button
    else:
        # No master data exists, show upload form
        return render_template('index.html', no_data=True)

@app.route('/upload')
def upload_form():
    """Show upload form"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Read the Excel file
            df = pd.read_excel(filepath)
            
            # Save as master data
            if save_master_data(df, file.filename):
                flash('File uploaded successfully and set as master data!')
            else:
                flash('File uploaded but failed to set as master data')
            
            # Create visualizations
            plots = create_visualizations(df)
            
            # Prepare metadata
            metadata = {
                'original_filename': file.filename,
                'upload_timestamp': datetime.now().isoformat(),
                'row_count': len(df),
                'column_count': len(df.columns),
                'columns': list(df.columns)
            }
            
            return render_template('results.html', 
                                 tables=[df.head(100).to_html(classes='data table table-striped', 
                                                              table_id='dataTable')],
                                 titles=['Uploaded Data'],
                                 plots=plots,
                                 metadata=metadata,
                                 show_upload_new=True)
                                 
        except Exception as e:
            flash(f'Error processing file: {str(e)}')
            return redirect(url_for('upload_form'))
    
    flash('Invalid file type. Please upload an Excel file (.xlsx or .xls)')
    return redirect(url_for('upload_form'))

@app.route('/data/refresh')
def refresh_data():
    """API endpoint to refresh data from master file"""
    df, metadata = load_master_data()
    
    if df is not None:
        return jsonify({
            'status': 'success',
            'row_count': len(df),
            'column_count': len(df.columns),
            'last_updated': metadata.get('upload_timestamp', 'Unknown')
        })
    else:
        return jsonify({'status': 'no_data'}), 404

@app.route('/health')
def health_check():
    df, metadata = load_master_data()
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'has_master_data': df is not None,
        'data_info': metadata if df is not None else None
    })

if __name__ == '__main__':
    # Get port from environment variable (Azure sets this to 80)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
