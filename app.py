import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import MySQLdb
from werkzeug.utils import secure_filename
from config import DB_CONFIG
import subprocess
import uuid

# Thêm đường dẫn tới OCRmyPDF
OCRMYPDF_PATH = r'e:\Chuyên đề HTTT\OCRmyPDFWeb\OCRmyPDF\src\ocrmypdf\__main__.py'

app = Flask(__name__)
app.secret_key = 'secret123'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
OUTPUT_FOLDER = "outputs"
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def get_db_connection():
    return MySQLdb.connect(**DB_CONFIG)

@app.route('/')
def home():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        # Kiểm tra lại mật khẩu xác nhận ở server-side
        if password != confirm_password:
            flash("Passwords do not match!")
            return render_template('register.html')
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        if cursor.fetchone():
            flash("Username already exists!")
        else:
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect('/login')
        conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            session['username'] = user[1]
            session['role'] = user[4]
            print("DEBUG user logged in:", session['username'])
            if user[4] == 'admin':
                return redirect('/admin_dashboard')
            else:
                return redirect('/upload')
        else:
            flash("Invalid credentials.")
    return render_template('login.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'username' not in session or session.get('role') != 'admin':
        flash("You don't have permission to access this page.")
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, points FROM users WHERE role != 'admin'")
    users = cursor.fetchall()
    conn.close()

    return render_template('admin.html', username=session['username'], users=users)

@app.route('/add_points', methods=['POST'])
def add_points():
    if 'username' not in session or session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang này.")
        return redirect('/login')

    username = request.form['username']
    points_to_add = int(request.form['points'])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points + %s WHERE username = %s AND role != 'admin'", (points_to_add, username))
    conn.commit()
    
    cursor.execute("INSERT INTO history (username, action, points_changed) VALUES (%s, %s, %s)", (username, 'add_balance', points_to_add))
    conn.commit()
    conn.close()

    flash(f"Added {points_to_add}$ to {username}'s wallet", "success")
    return redirect('/admin_dashboard')

@app.route('/view_user_history/<username>')
def view_user_history(username):
    if 'username' not in session or session.get('role') != 'admin':
        flash("Bạn không có quyền truy cập trang này.")
        return redirect('/login')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM history WHERE username = %s ORDER BY timestamp DESC", (username,))
    history_records = cursor.fetchall()
    conn.close()

    return render_template('user_history.html', username=username, history_records=history_records)

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect('/login')
    return render_template('dashboard.html', username=session['username'])

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if 'username' not in session:
        return redirect('/login')
    
    # Lấy số điểm của người dùng từ database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM users WHERE username = %s", (session['username'],))
    user_data = cursor.fetchone()
    conn.close()
    
    user_points = user_data[0] if user_data else 0
    
    if request.method == 'POST':
        # Kiểm tra xem có yêu cầu Ajax không
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Kiểm tra xem file có được tải lên không
        if 'file' not in request.files:
            if is_ajax:
                return jsonify({"status": "error", "message": "No file part"})
            flash("No file part")
            return redirect(request.url)
            
        file = request.files['file']
        if file.filename == '':
            if is_ajax:
                return jsonify({"status": "error", "message": "No file selected"})
            flash("No file selected")
            return redirect(request.url)

        # Check if file is a PDF
        if not file.filename.endswith(".pdf"):
            if is_ajax:
                return jsonify({"status": "error", "message": "Please upload a PDF file"})
            flash("Please upload a PDF file.")
            return redirect(request.url)
            
        # Kiểm tra và trừ điểm người dùng
        POINTS_COST = 2  # Số điểm cần trừ cho mỗi lần chuyển đổi
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Kiểm tra người dùng có đủ điểm không
        cursor.execute("SELECT points FROM users WHERE username = %s", (session['username'],))
        current_points = cursor.fetchone()[0]
        
        if current_points < POINTS_COST:
            conn.close()
            error_message = f"You don't have enough points to perform the conversion. Need {POINTS_COST} $."
            if is_ajax:
                return jsonify({"status": "error", "message": error_message})
            flash(error_message)
            return redirect(request.url)
        
        # Trừ điểm người dùng
        cursor.execute("UPDATE users SET points = points - %s WHERE username = %s", 
                      (POINTS_COST, session['username']))
        
        # Lấy số điểm mới
        cursor.execute("SELECT points FROM users WHERE username = %s", (session['username'],))
        updated_points = cursor.fetchone()[0]
        
        # Thêm vào lịch sử
        cursor.execute("INSERT INTO history (username, action, points_changed) VALUES (%s, %s, %s)", 
                      (session['username'], 'convert_pdf', -POINTS_COST))
        
        conn.commit()
        conn.close()

        # Lưu file tải lên
        filename = secure_filename(file.filename)
        file_id = str(uuid.uuid4())
        input_path = os.path.join(UPLOAD_FOLDER, f"{file_id}.pdf")
        file.save(input_path)

        # Đặt đường dẫn output OCR
        output_path = os.path.join(OUTPUT_FOLDER, f"{file_id}_ocr.pdf")

        try:
            # Thực hiện OCR với môi trường đúng
            env = os.environ.copy()
            env['PYTHONPATH'] = r'e:\Chuyên đề HTTT\OCRmyPDFWeb\OCRmyPDF'  # Đặt PYTHONPATH
            
            ocr_command = [
                'python', 
                '-m',
                'ocrmypdf',
                '--deskew',
                '--force-ocr',
                input_path, 
                output_path
            ]
            
            # Chạy quá trình OCR với môi trường đã được thiết lập
            process = subprocess.run(
                ocr_command,
                capture_output=True,
                text=True,
                check=True,
                env=env
            )
            
            success_message = f'File "{filename}" has been successfully processed with OCR.'
            
            if is_ajax:
                download_url = url_for('download_file', file_id=file_id)
                preview_url = url_for('preview_file', file_id=file_id)
                
                return jsonify({
                    "status": "success", 
                    "message": success_message,
                    "download_url": download_url,
                    "preview_url": preview_url,
                    "updated_points": updated_points
                })
                
            flash(success_message, "success")
            return send_file(output_path, as_attachment=True, download_name=f"ocr_{filename}")

        except subprocess.CalledProcessError as e:
            error_message = f"Lỗi khi xử lý file: {e.stderr}"
            if is_ajax:
                return jsonify({"status": "error", "message": error_message})
            flash(error_message, "error")
            return redirect(request.url)

    return render_template('upload.html', user_points=user_points)

@app.route('/download/<file_id>')
def download_file(file_id):
    if 'username' not in session:
        return redirect('/login')
        
    output_path = os.path.join(OUTPUT_FOLDER, f"{file_id}_ocr.pdf")
    if os.path.exists(output_path):
        return send_file(output_path, as_attachment=True)
    else:
        flash("File does not exist or has been deleted.")
        return redirect('/upload')

@app.route('/qrbank')
def qrbank():
    if 'username' not in session:
        return redirect('/login')
    
    # Cập nhật lại điểm người dùng
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM users WHERE username = %s", (session['username'],))
    result = cursor.fetchone()
    conn.close()

    user_points = result[0] if result else 0
    session['user_points'] = user_points

    return render_template('qrbank.html', username=session['username'], user_points=user_points)

@app.route('/preview/<file_id>')
def preview_file(file_id):
    if 'username' not in session:
        return redirect('/login')
        
    output_path = os.path.join(OUTPUT_FOLDER, f"{file_id}_ocr.pdf")
    if os.path.exists(output_path):
        return send_file(output_path, as_attachment=False)
    else:
        flash("File does not exist or has been deleted.")
        return redirect('/upload')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    session.pop('user_points', None)
    return redirect('/login')

if __name__ == '__main__':
    app.run(debug=True)
