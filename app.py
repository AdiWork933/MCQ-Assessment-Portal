import os
import json
import glob
from dotenv import load_dotenv
import google.generativeai as genai
from fpdf import FPDF
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import base64
import hashlib
import datetime
import random
import string
from werkzeug.utils import secure_filename

load_dotenv()

# Helper functions for password encryption/decryption

def get_fernet():
    key = os.getenv('PASSWORD_SECRET_KEY', 'defaultkey')
    # Fernet key must be 32 url-safe base64-encoded bytes
    key_bytes = hashlib.sha256(key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

def encrypt_password(plain_password):
    f = get_fernet()
    return f.encrypt(plain_password.encode()).decode()

def decrypt_password(encrypted_password):
    if not encrypted_password:
        return ''
    try:
        f = get_fernet()
        return f.decrypt(encrypted_password.encode()).decode()
    except Exception:
        return '[decryption error]'

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super_secret_key_change_me") # A strong secret key is crucial for session security
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Add custom template filter for basename
@app.template_filter('basename')
def basename_filter(path):
    """Template filter to get the basename of a file path."""
    return os.path.basename(path)

# Configure upload folder
UPLOAD_FOLDER = os.path.join('static', 'pdfs')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Define file paths
SUBMISSIONS_FILE = "submissions.json"
USERS_FILE = "users.json"
QUESTION_BANK_FILE = "question_bank.json" # New file for storing generated questions

# -------------- UTILITY FUNCTIONS --------------

def load_users():
    """Loads existing users from the JSON file."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                else:
                    return {} # Return empty dict if file is empty
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {USERS_FILE}. Starting with empty users.")
            return {}
    return {}

def save_users(users_data):
    """Saves user data to the JSON file."""
    with open(USERS_FILE, "w") as f:
        json.dump(users_data, f, indent=2)

def load_question_bank():
    """Loads existing questions from the question bank JSON file."""
    if os.path.exists(QUESTION_BANK_FILE):
        try:
            with open(QUESTION_BANK_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
                    else:
                        return [] # If file contains something not a list, treat as empty
                else:
                    return []
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {QUESTION_BANK_FILE}. Starting with empty question bank.")
            return []
    return []

def save_questions_to_bank(questions_data):
    """Saves a list of questions to the question bank JSON file, overwriting existing content."""
    with open(QUESTION_BANK_FILE, "w") as f:
        json.dump(questions_data, f, indent=2)

def append_questions_to_bank(new_questions):
    """Appends new questions to the existing question bank JSON file."""
    existing_questions = load_question_bank()
    existing_questions.extend(new_questions)
    save_questions_to_bank(existing_questions)


def generate_mcqs(subject, level, count):
    """
    Generates multiple-choice questions in JSON format using the Gemini API.
    First, it tries to retrieve questions from the question_bank.json based on subject and level.
    If not enough questions are found, it generates new ones and appends them to the bank.
    """
    all_questions_in_bank = load_question_bank()
    
    # Filter existing questions by subject and level
    filtered_questions = [
        q for q in all_questions_in_bank 
        if q.get("subject", "").lower() == subject.lower() and 
           q.get("Difficulty Level", "").lower() == level.lower()
    ]
    
    if len(filtered_questions) >= count:
        # If enough questions exist, randomly select 'count' of them
        return random.sample(filtered_questions, count)
    else:
        # If not enough, calculate how many more are needed
        needed_count = count - len(filtered_questions)
        
        # Ensure needed_count is positive before generating
        if needed_count <= 0:
            return random.sample(filtered_questions, count)

        prompt = f"""
        Generate {needed_count} multiple choice questions (MCQs) for the subject '{subject}' at the '{level}' difficulty level.
        Each question should have 4 options.
        Provide the output in a JSON array format, where each object in the array represents a question.
        Each question object should have the following keys:
        - "question": The text of the question.
        - "options": A JSON array of 4 strings for the options.
        - "correct_answer": The exact string of the correct option.
        - "Difficulty Level": The difficulty level (e.g., "Beginner", "Intermediate", "Advanced").
        - "subject": The subject of the question.

        Example JSON structure for one question:
        {{
            "question": "What is the capital of France?",
            "options": ["Berlin", "Madrid", "Paris", "Rome"],
            "correct_answer": "Paris",
            "Difficulty Level": "Beginner",
            "subject": "Geography"
        }}
        """
        model = genai.GenerativeModel(model_name="models/gemini-2.0-flash")
        try:
            response = model.generate_content(prompt)
            raw_generated_json = response.text
            
            # Parse and validate newly generated questions
            newly_generated_mcqs = parse_mcqs_from_gemini(raw_generated_json)
            
            # Append generated questions to the question bank
            if newly_generated_mcqs:
                append_questions_to_bank(newly_generated_mcqs)
                print(f"Appended {len(newly_generated_mcqs)} new questions to the question bank.")
            
            # Combine existing filtered questions with newly generated ones
            combined_questions = filtered_questions + newly_generated_mcqs
            
            # If after generation, we still don't have enough (e.g., Gemini couldn't generate all),
            # return what we have, up to 'count'.
            return random.sample(combined_questions, min(count, len(combined_questions)))
            
        except Exception as e:
            print(f"Error generating questions from Gemini: {e}")
            return filtered_questions # Return existing questions even if generation fails

def parse_mcqs_from_gemini(raw_json_text):
    """
    Parses the raw JSON text response from the Gemini model into a structured list of questions,
    and performs validation. This is specifically for processing Gemini's direct output.
    """
    questions = []
    try:
        # Clean the string to ensure it's valid JSON
        # Sometimes Gemini might include markdown ```json ... ``` or extra text
        if raw_json_text.strip().startswith("```json"):
            raw_json_text = raw_json_text.strip()[7:]
            if raw_json_text.strip().endswith("```"):
                raw_json_text = raw_json_text.strip()[:-3]
        
        data = json.loads(raw_json_text)

        if not isinstance(data, list):
            print("Error: JSON data from Gemini is not a list of questions.")
            return []

        for item in data:
            if not isinstance(item, dict):
                print(f"Warning: Skipping non-dictionary item in Gemini response: {item}")
                continue

            question = item.get("question")
            options = item.get("options")
            correct_answer = item.get("correct_answer")
            difficulty_level = item.get("Difficulty Level") # New field
            subject = item.get("subject") # New field

            if not all([question, options, correct_answer, difficulty_level, subject]):
                print(f"Warning: Skipping question due to missing fields from Gemini: {item}")
                continue

            if not (isinstance(options, list) and len(options) == 4 and
                            all(isinstance(opt, str) for opt in options)):
                print(f"Warning: Skipping question due to invalid options format from Gemini: {item}")
                continue

            if correct_answer not in options:
                print(f"Warning: Skipping question where correct answer is not in options from Gemini: {item}")
                continue

            questions.append({
                "question": question,
                "options": options,
                "correct_answer": correct_answer,
                "Difficulty Level": difficulty_level,
                "subject": subject
            })
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from Gemini response: {e}. Raw text: {raw_json_text[:500]}...") # Print first 500 chars of problematic text
    except Exception as e:
        print(f"An unexpected error occurred during parsing Gemini MCQs: {e}")
    return questions



def create_pdf_report(submission_data, filename=None):
    """
    Creates a PDF report for a single submission, with Unicode support.
    Saves the PDF in the static/pdfs directory.
    """
    user_info = submission_data.get('user_info', {})
    answers_data = submission_data.get('answers', [])

    name_cleaned = user_info.get('name', 'candidate').replace(" ", "_").lower()
    if filename is None:
        filename = f"{name_cleaned}_report_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    
    # Ensure the filename is safe and has .pdf extension
    filename = secure_filename(filename)
    if not filename.lower().endswith('.pdf'):
        filename += '.pdf'
    
    # Create the full path in the static/pdfs directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    total_questions = len(answers_data)
    correct_count = sum(1 for ans_item in answers_data if ans_item.get('is_correct', False))

    pdf = FPDF()
    pdf.add_page()
    
    # Add Unicode fonts (DejaVuSans for regular, DejaVuSans-Bold for bold)
    try:
        # Construct paths to the font files relative to the script's directory
        font_path_regular = os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans.ttf')
        font_path_bold = os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans-Bold.ttf') # Path to bold font

        # Register the regular font
        pdf.add_font('DejaVu', '', font_path_regular, uni=True)
        # Register the bold font for the 'B' style
        pdf.add_font('DejaVu', 'B', font_path_bold, uni=True) 
        
        pdf.set_font('DejaVu', '', 12) # Set default font to regular DejaVu
    except RuntimeError as e: # Catch RuntimeError for font loading issues
        print(f"Error loading DejaVu font: {e}. Falling back to Arial. Unicode characters may not render correctly.")
        pdf.set_font("Arial", size=12)

    # Report Card Header
    pdf.set_font("DejaVu", 'B', 16) # This will now use the registered bold font
    pdf.cell(0, 10, txt="MCQ Submission Report", ln=True, align="C")
    pdf.ln(5)

    # Candidate Information
    pdf.set_font("DejaVu", 'B', 12) # This will also use the registered bold font
    pdf.cell(0, 10, txt="Candidate Information:", ln=True)
    pdf.set_font("DejaVu", '', 12) # This reverts to the regular font
    pdf.cell(0, 7, txt=f"Name: {user_info.get('name', 'N/A')}", ln=True)
    pdf.cell(0, 7, txt=f"Stream: {user_info.get('stream', 'N/A')}", ln=True)
    pdf.cell(0, 7, txt=f"Phone: {user_info.get('phone', 'N/A')}", ln=True)
    pdf.ln(5)

    # Results Summary
    pdf.set_font("DejaVu", 'B', 12) # Bold
    pdf.cell(0, 10, txt="Results Summary:", ln=True)
    pdf.set_font("DejaVu", '', 12) # Regular
    pdf.cell(0, 7, txt=f"Total Questions: {total_questions}", ln=True)
    pdf.cell(0, 7, txt=f"Correct Answers: {correct_count}", ln=True)
    pdf.cell(0, 7, txt=f"Score: {correct_count}/{total_questions}", ln=True)
    pdf.ln(10)

    # Detailed Answers
    pdf.set_font("DejaVu", 'B', 14) # Bold
    pdf.cell(0, 10, txt="Detailed Answers:", ln=True)
    pdf.set_font("DejaVu", '', 10) # Smaller, regular font for details

    initial_x = pdf.l_margin # Get the left margin to reset x position
    line_height = 7 # Consistent line height for clarity

    for idx, ans_item in enumerate(answers_data, 1):
        question_text = ans_item.get('question', 'N/A')
        user_answer = ans_item.get('user_answer', 'Not answered')
        correct_answer = ans_item.get('correct_answer', 'N/A')
        is_correct = ans_item.get('is_correct', False)

        result_text = "Correct" if is_correct else "Incorrect"
        result_color = (0, 128, 0) if is_correct else (255, 0, 0)

        # Ensure cursor is at the left margin before starting a new question block
        pdf.set_x(initial_x)

        pdf.set_fill_color(240, 240, 240) # Light grey background
        pdf.multi_cell(0, line_height, f"Q{idx}: {question_text}", border=1, align='L', fill=True)

        pdf.set_x(initial_x) # Reset X after multi_cell potentially moves it
        pdf.multi_cell(0, line_height, f"Your Answer: {user_answer}", border=1, align='L', fill=True)

        pdf.set_x(initial_x) # Reset X
        pdf.multi_cell(0, line_height, f"Correct Answer: {correct_answer}", border=1, align='L', fill=True)

        pdf.set_x(initial_x) # Reset X
        pdf.set_text_color(*result_color)
        pdf.multi_cell(0, line_height, f"Result: {result_text}", border=1, align='L', fill=True)
        pdf.set_text_color(0, 0, 0) # Reset color to black

        pdf.ln(5) # Add a small break between question blocks

    # Save the PDF to the static/pdfs directory
    pdf.output(filepath)
    return filepath

def load_submissions():
    """Loads existing submissions from the JSON file."""
    if os.path.exists(SUBMISSIONS_FILE):
        try:
            with open(SUBMISSIONS_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
                    else:
                        return [data] # Handle case where file might contain a single object, not a list
                else:
                    return []
        except json.JSONDecodeError:
            print("Error decoding JSON file for submissions. Starting with an empty list.")
            return []
    return []

def save_submission(submission_data):
    """Appends a new submission to the JSON file with username and timestamp."""
    submissions = load_submissions()
    # Add username and ensure timestamp is included
    if 'timestamp' not in submission_data:
        submission_data['timestamp'] = datetime.datetime.now().isoformat()
    if 'username' not in submission_data and 'user_info' in submission_data:
        submission_data['username'] = submission_data['user_info'].get('username', 'anonymous')
    submissions.append(submission_data)
    with open(SUBMISSIONS_FILE, 'w') as f:
        json.dump(submissions, f, indent=2)

# New: Context processor to inject current_year into all templates
@app.context_processor
def inject_current_year():
    """Injects the current year into all templates."""
    return {'current_year': datetime.datetime.now().year}

# -------------- AUTHENTICATION ROUTES --------------

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    unique_id = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        stream = request.form['stream']
        phone = request.form['phone']

        users = load_users()
        if username in users:
            flash('Username already exists. Please choose a different one.', 'danger')
            return render_template('signup.html', username=username, name=name, stream=stream, phone=phone)

        def generate_unique_id(existing_ids):
            while True:
                uid = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                if uid not in existing_ids:
                    return uid
        existing_unique_ids = {user.get('unique_id') for user in users.values() if 'unique_id' in user}
        unique_id = generate_unique_id(existing_unique_ids)

        hashed_password = generate_password_hash(password)
        users[username] = {
            'password': hashed_password,
            'plain_password': password,   # Store plain password for admin view
            'name': name,
            'stream': stream,
            'phone': phone,
            'unique_id': unique_id
        }
        save_users(users)
        flash('Account created successfully! Please log in. Your Unique ID: {}'.format(unique_id), 'success')
        return render_template('signup.html', unique_id=unique_id)
    return render_template('signup.html')

@app.route('/forget_password', methods=['GET', 'POST'])
def forget_password():
    message = None
    if request.method == 'POST':
        user_identifier = request.form['user_identifier']
        phone = request.form['phone']
        new_password = request.form['new_password']
        users = load_users()
        user = users.get(user_identifier)
        username_found = user_identifier if user else None
        if not user:
            for uname, udata in users.items():
                if udata.get('unique_id') == user_identifier:
                    user = udata
                    username_found = uname
                    break
        if user:
            if user.get('phone') == phone:
                users[username_found]['password'] = generate_password_hash(new_password)
                users[username_found]['plain_password'] = new_password   # Update plain password
                save_users(users)
                flash('Password has been reset successfully! Please log in.', 'success')
                return redirect(url_for('login'))
            else:
                message = 'Phone number does not match our records.'
        else:
            message = 'No user found with that username or unique ID.'
        return render_template('forget_password.html', message=message)
    return render_template('forget_password.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_identifier = request.form['username']
        password = request.form['password']
        admin_username = os.getenv('ADMIN_USERNAME')
        admin_password = os.getenv('ADMIN_PASSWORD')

        # Check if admin login
        if user_identifier == admin_username and password == admin_password:
            session['logged_in'] = True
            session['is_admin'] = True
            session['username'] = admin_username
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin_panel'))

        users = load_users()
        user = users.get(user_identifier)
        username_found = user_identifier if user else None
        if not user:
            for uname, udata in users.items():
                if udata.get('unique_id') == user_identifier:
                    user = udata
                    username_found = uname
                    break
        if user and check_password_hash(user['password'], password):
            session['logged_in'] = True
            session['is_admin'] = False
            session['username'] = username_found
            session['user_info'] = {
                'name': user.get('name', ''),
                'stream': user.get('stream', ''),
                'phone': user.get('phone', ''),
                'unique_id': user.get('unique_id', '')
            }
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username/unique ID or password.', 'danger')
    return render_template('login.html')

@app.route('/admin_panel')
def admin_panel():
    if not session.get('logged_in') or not session.get('is_admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('login'))
    users = load_users()
    total_users = len(users)
    user_details = [
        {'username': uname, **udata} for uname, udata in users.items()
    ]
    questions = load_question_bank()
    total_questions = len(questions)
    total_answers = 0
    try:
        with open(SUBMISSIONS_FILE, 'r') as f:
            submissions = json.load(f)
            for sub in submissions:
                total_answers += len(sub.get('answers', []))
    except Exception:
        total_answers = 0
    
    # Get list of PDFs
    pdf_files = []
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename.endswith('.pdf'):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file_size = os.path.getsize(file_path) / 1024  # Size in KB
            file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            pdf_files.append({
                'name': filename,
                'size': f"{file_size:.1f} KB",
                'uploaded': file_mtime.strftime('%Y-%m-%d %H:%M:%S')
            })
    
    return render_template('admin_panel.html', 
                         total_users=total_users, 
                         user_details=user_details, 
                         total_questions=total_questions, 
                         total_answers=total_answers,
                         pdf_files=pdf_files)

@app.route('/admin_edit_user/<username>', methods=['GET', 'POST'])
def admin_edit_user(username):
    if not session.get('logged_in') or not session.get('is_admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('login'))
    users = load_users()
    user = users.get(username)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        user['name'] = request.form['name']
        user['stream'] = request.form['stream']
        user['phone'] = request.form['phone']
        user['unique_id'] = request.form['unique_id']
        new_password = request.form['password']
        if new_password:
            user['password'] = generate_password_hash(new_password)
            user['plain_password'] = new_password
        users[username] = user
        save_users(users)
        flash('User details updated successfully.', 'success')
        return redirect(url_for('admin_panel'))
    return render_template('admin_edit_user.html', username=username, user=user)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('user_info', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# -------------- MAIN APPLICATION ROUTES --------------

@app.route('/')
@login_required
def index():
    return render_template('index.html', user_info=session.get('user_info', {}))

@app.route('/generate_mcqs', methods=['GET', 'POST'])
@login_required
def mcq_generation():
    if request.method == 'POST':
        subject = request.form['subject']
        level = request.form['level']
        count = int(request.form['count'])

        if not subject:
            flash("Please enter a subject to generate questions.", 'warning')
            return render_template('mcq_generation.html', user_info=session.get('user_info', {}),
                                   subject=subject, level=level, count=count)

        # Call generate_mcqs which now handles loading/generating/saving
        questions = generate_mcqs(subject, level, count)

        if questions:
            session['questions'] = questions
            session['user_selections'] = [None] * len(questions)
            return redirect(url_for('mcq_answering'))
        else:
            flash("Failed to retrieve or generate valid MCQs. Try different parameters.", 'danger')
            return render_template('mcq_generation.html', user_info=session.get('user_info', {}),
                                   subject=subject, level=level, count=count)

    return render_template('mcq_generation.html', user_info=session.get('user_info', {}))

@app.route('/answer_mcqs', methods=['GET', 'POST'])
@login_required
def mcq_answering():
    if 'questions' not in session or not session['questions']:
        flash("No questions generated. Please generate MCQs first.", 'warning')
        return redirect(url_for('mcq_generation'))

    questions = session['questions']

    user_selections = session.get('user_selections', [None] * len(questions))
    if len(user_selections) != len(questions):
        user_selections = [None] * len(questions)
        session['user_selections'] = user_selections

    if request.method == 'POST':
        current_answers = []
        all_answered = True

        new_selections_from_form = [None] * len(questions)

        for i, q_data in enumerate(questions):
            selected_number = request.form.get(f'q_{i}')
            options = q_data['options']
            selected_option = None
            valid = True
            if selected_number is None or selected_number.strip() == '':
                all_answered = False
                new_selections_from_form[i] = ''
                valid = False
            else:
                try:
                    selected_idx = int(selected_number) - 1
                    if 0 <= selected_idx < len(options):
                        selected_option = options[selected_idx]
                        new_selections_from_form[i] = selected_number
                    else:
                        all_answered = False
                        new_selections_from_form[i] = selected_number
                        valid = False
                except ValueError:
                    all_answered = False
                    new_selections_from_form[i] = selected_number
                    valid = False

            is_correct = (selected_option == q_data['correct_answer']) if valid else False

            current_answers.append({
                "question": q_data['question'],
                "options": q_data['options'],
                "user_answer": selected_option if valid else selected_number,
                "correct_answer": q_data['correct_answer'],
                "is_correct": is_correct,
                "answer_number": selected_number
            })

        session['user_selections'] = new_selections_from_form

        if not all_answered:
            flash("Please answer all questions before submitting.", 'warning')
            return render_template('mcq_answering.html', questions=questions, user_info=session.get('user_info', {}),
                                   user_selections=session['user_selections'])
        else:
            full_submission_data = {
                "user_info": session['user_info'],
                "questions_generated": [q['question'] for q in questions],
                "answers": current_answers,
                "timestamp": datetime.datetime.now().isoformat()
            }

            # Add username to submission data
            full_submission_data['username'] = session.get('username')
            full_submission_data['subject'] = session.get('subject', 'General')
            
            # Save submission first to get the ID
            save_submission(full_submission_data)
            
            # Generate PDF with the submission data
            pdf_filename = create_pdf_report(full_submission_data)
            
            # Update the submission with the PDF path
            full_submission_data['pdf_path'] = pdf_filename
            save_submission(full_submission_data)

            session['last_pdf_path'] = pdf_filename
            session['submission_complete'] = True
            session.pop('questions', None)
            session.pop('user_selections', None)

            flash('Your answers have been submitted and saved!', 'success')
            return redirect(url_for('report_display'))

    return render_template('mcq_answering.html', questions=questions, user_info=session.get('user_info', {}),
                           user_selections=user_selections)

@app.route('/report')
@login_required
def report_display():
    if not session.get('submission_complete'):
        flash("No submission found to display report.", 'warning')
        return redirect(url_for('index'))

    pdf_path = session.get('last_pdf_path')
    if pdf_path and os.path.exists(pdf_path):
        filename = os.path.basename(pdf_path)
    else:
        filename = None

    return render_template('report.html', filename=filename)

@app.route('/download_report/<path:filename>')
@login_required
def download_report(filename):
    """Download a specific report file."""
    # Check if the file exists in the PDFs directory
    file_path = os.path.join('static', 'pdfs', filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        flash("Report file not found.", 'danger')
        return redirect(url_for('my_submissions'))

@app.route('/view_submission/<int:submission_id>')
@login_required
def view_submission(submission_id):
    """View details of a specific submission."""
    username = session.get('username')
    all_submissions = load_submissions()
    
    # Find the submission by ID and verify ownership
    if 0 <= submission_id < len(all_submissions):
        submission = all_submissions[submission_id]
        if submission.get('username') == username:
            # Store the PDF path in session for the report display
            session['last_pdf_path'] = submission.get('pdf_path', '')
            session['submission_complete'] = True
            return redirect(url_for('report_display'))
    
    flash('Submission not found or access denied.', 'danger')
    return redirect(url_for('my_submissions'))

@app.route('/start_new_quiz')
@login_required
def start_new_quiz():
    session.pop('questions', None)
    session.pop('user_selections', None)
    session.pop('submission_complete', None)
    session.pop('last_pdf_path', None)
    flash("You can now start a new quiz.", 'info')
    return redirect(url_for('index'))

@app.route('/admin/upload_pdf', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'message': 'File uploaded successfully'}), 200
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/admin/delete_pdf/<filename>')
def delete_pdf(filename):
    if not session.get('logged_in') or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({'message': 'File deleted successfully'}), 200
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/admin/delete_all_pdfs', methods=['POST'])
def delete_all_pdfs():
    if not session.get('logged_in') or not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.endswith('.pdf'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                os.remove(file_path)
        return jsonify({'message': 'All PDFs deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/download_pdf/<filename>')
def download_pdf(filename):
    if not session.get('logged_in') or not session.get('is_admin'):
        return 'Unauthorized', 403
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    
    return 'File not found', 404

@app.route('/my_submissions')
@login_required
def my_submissions():
    """Display the current user's submission history."""
    # Ensure user is logged in
    if 'username' not in session:
        flash('Please log in to view your submissions.', 'warning')
        return redirect(url_for('login'))
    
    # Initialize user_info in session if it doesn't exist
    if 'user_info' not in session:
        users = load_users()
        user_data = users.get(session['username'], {})
        session['user_info'] = {
            'name': user_data.get('name', ''),
            'stream': user_data.get('stream', ''),
            'phone': user_data.get('phone', ''),
            'unique_id': user_data.get('unique_id', '')
        }
    
    username = session['username']
    all_submissions = load_submissions()
    
    # Filter submissions for the current user
    user_submissions = []
    for sub in all_submissions:
        if sub.get('username') == username:
            # Calculate score
            correct_answers = sum(1 for a in sub.get('answers', []) if a.get('is_correct', False))
            total_questions = len(sub.get('answers', [])) or 1
            
            user_submissions.append({
                'timestamp': sub.get('timestamp'),
                'score': f"{correct_answers}/{total_questions}",
                'subject': sub.get('subject', 'General'),
                'pdf_path': sub.get('pdf_path', '')
            })
    
    # Sort by timestamp, newest first
    user_submissions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Format dates for display
    for sub in user_submissions:
        try:
            dt = datetime.datetime.fromisoformat(sub['timestamp'])
            sub['formatted_date'] = dt.strftime('%B %d, %Y %I:%M %p')
        except (ValueError, KeyError):
            sub['formatted_date'] = 'Unknown date'
    
    return render_template('my_submissions.html', submissions=user_submissions)

if __name__ == '__main__':
    # Create necessary files if they don't exist
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(SUBMISSIONS_FILE):
        with open(SUBMISSIONS_FILE, 'w') as f:
            json.dump([], f)
    if not os.path.exists(QUESTION_BANK_FILE):
        with open(QUESTION_BANK_FILE, 'w') as f:
            json.dump([], f)
    
    # Create upload folder if it doesn't exist
    os.makedirs('static/pdfs', exist_ok=True)
    
    app.run(debug=True)