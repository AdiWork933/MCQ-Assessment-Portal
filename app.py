import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from fpdf import FPDF
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import base64
import hashlib
import datetime
import random
import string

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

# Define file paths
SUBMISSIONS_FILE = "submissions.json"
USERS_FILE = "users.json"
QUESTION_BANK_FILE = "question_bank.json" # New file for storing generated questions
MAIN_EXAM_FILE = "main_exam.json" # Admin-configured main exam
REPORTS_DIR = "reports"

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


def load_main_exam():
    """Load the admin-configured main exam configuration."""
    if os.path.exists(MAIN_EXAM_FILE):
        try:
            with open(MAIN_EXAM_FILE, "r") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        # Normalize expected fields
                        data.setdefault("active", False)
                        data.setdefault("duration_minutes", 0)
                        data.setdefault("questions", [])
                        return data
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {MAIN_EXAM_FILE}. Starting with inactive main exam.")
    return {"active": False, "duration_minutes": 0, "questions": [], "access": {"mode": "all", "user_ids": []}}


def save_main_exam(config):
    """Persist the main exam configuration to disk."""
    with open(MAIN_EXAM_FILE, "w") as f:
        json.dump(config, f, indent=2)


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
    """
    user_info = submission_data.get('user_info', {})
    answers_data = submission_data.get('answers', [])

    name_cleaned = user_info.get('name', 'candidate').replace(" ", "_").lower()
    if filename is None:
        filename = f"{name_cleaned}_report_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"

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

    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)
    report_path = os.path.join(REPORTS_DIR, filename)
    pdf.output(report_path)
    return report_path

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
    """Appends a new submission to the JSON file."""
    all_submissions = load_submissions()
    all_submissions.append(submission_data)
    with open(SUBMISSIONS_FILE, "w") as f:
        json.dump(all_submissions, f, indent=2)

# New: Context processor to inject current_year into all templates
@app.context_processor
def inject_current_year():
    """Injects the current year into all templates."""
    return {'current_year': datetime.datetime.now().year}

# -------------- AUTHENTICATION ROUTES --------------

@app.route('/signup', methods=['GET', 'POST'])
def signup():
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
        # Show the unique code on the login page only once via flash
        flash('Account created successfully! Your Unique ID: {}'.format(unique_id), 'success')
        return redirect(url_for('login'))
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
    submissions = []
    try:
        with open(SUBMISSIONS_FILE, 'r') as f:
            submissions = json.load(f)
            for sub in submissions:
                total_answers += len(sub.get('answers', []))
    except Exception:
        total_answers = 0
        submissions = []

    # Build enriched submission summaries for admin view
    submission_rows = []
    for sub in submissions:
        user_info = sub.get('user_info', {})
        answers = sub.get('answers', [])
        correct = sum(1 for a in answers if a.get('is_correct'))
        total = len(answers)
        submission_rows.append({
            'name': user_info.get('name', 'N/A'),
            'exam_type': sub.get('exam_type', 'self_exam'),
            'score': f"{correct}/{total}",
            'timestamp': sub.get('timestamp', ''),
            'unique_id': user_info.get('unique_id', ''),
            'phone': user_info.get('phone', '')
        })

    # Sort newest first
    try:
        submission_rows.sort(key=lambda s: s.get('timestamp', ''), reverse=True)
    except Exception:
        pass

    main_exam = load_main_exam()
    return render_template('admin_panel.html', total_users=total_users, user_details=user_details, total_questions=total_questions, total_answers=total_answers, main_exam_active=main_exam.get('active', False), submission_rows=submission_rows)


@app.route('/admin_delete_submission', methods=['POST'])
def admin_delete_submission():
    if not session.get('logged_in') or not session.get('is_admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('login'))

    ts = request.form.get('timestamp', '')
    exam_type = request.form.get('exam_type', '')
    name = request.form.get('name', '')
    phone = request.form.get('phone', '')
    uid = request.form.get('unique_id', '')

    subs = load_submissions()
    removed = False
    new_list = []
    for s in subs:
        if removed:
            new_list.append(s)
            continue
        u = s.get('user_info', {})
        if s.get('timestamp') == ts and s.get('exam_type') == exam_type and (
            (uid and u.get('unique_id') == uid) or (name and phone and u.get('name') == name and u.get('phone') == phone)
        ):
            removed = True
            continue
        new_list.append(s)

    with open(SUBMISSIONS_FILE, 'w') as f:
        json.dump(new_list, f, indent=2)

    if removed:
        flash('Submission deleted.', 'success')
    else:
        flash('Submission not found.', 'warning')
    return redirect(url_for('admin_panel'))

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


@app.route('/admin_delete_user/<username>', methods=['POST'])
def admin_delete_user(username):
    if not session.get('logged_in') or not session.get('is_admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('login'))

    admin_username = os.getenv('ADMIN_USERNAME')
    if username == admin_username:
        flash('Cannot delete the admin account.', 'warning')
        return redirect(url_for('admin_panel'))

    users = load_users()
    if username not in users:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_panel'))

    # Keep unique_id to optionally clean submissions
    deleted_user = users.pop(username)
    save_users(users)

    # Optionally remove submissions of this user
    try:
        subs = load_submissions()
        uid = deleted_user.get('unique_id')
        name = deleted_user.get('name')
        phone = deleted_user.get('phone')
        filtered = []
        for s in subs:
            u = s.get('user_info', {})
            if uid and u.get('unique_id') == uid:
                continue
            if name and phone and u.get('name') == name and u.get('phone') == phone:
                continue
            filtered.append(s)
        with open(SUBMISSIONS_FILE, 'w') as f:
            json.dump(filtered, f, indent=2)
    except Exception:
        pass

    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin_panel'))


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
    users = load_users()
    username = session.get('username')
    user_record = users.get(username, {}) if username else {}
    main_exam = load_main_exam()
    # Access check for button visibility
    can_access = False
    if main_exam.get('active'):
        access = main_exam.get('access', {"mode": "all", "user_ids": []})
        if access.get('mode') == 'all':
            can_access = True
        else:
            if username and username in access.get('user_ids', []):
                can_access = True
    return render_template('index.html', user_info=session.get('user_info', {}), main_exam_active=main_exam.get('active', False), main_exam_attempted=user_record.get('main_exam_attempted', False), main_exam_can_access=can_access)

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
                "timestamp": datetime.datetime.now().isoformat(),
                "exam_type": "self_exam"
            }

            pdf_path = create_pdf_report(full_submission_data)
            full_submission_data["report_file"] = os.path.basename(pdf_path)
            save_submission(full_submission_data)

            session['last_pdf_path'] = pdf_path
            session['submission_complete'] = True
            session.pop('questions', None)
            session.pop('user_selections', None)

            flash('Your answers have been submitted and saved!', 'success')
            return redirect(url_for('report_display'))

    return render_template('mcq_answering.html', questions=questions, user_info=session.get('user_info', {}),
                           user_selections=user_selections)


# --------- ADMIN: Configure Main Exam ---------
@app.route('/admin/main_exam', methods=['GET', 'POST'])
def admin_main_exam():
    if not session.get('logged_in') or not session.get('is_admin'):
        flash('Admin access required.', 'danger')
        return redirect(url_for('login'))

    current_config = load_main_exam()

    if request.method == 'POST':
        try:
            duration_minutes = int(request.form.get('duration_minutes', '0'))
        except ValueError:
            duration_minutes = 0

        # Option A: Build from question bank using subject/level/count
        subject = request.form.get('subject', '').strip()
        level = request.form.get('level', '').strip()
        try:
            count = int(request.form.get('count', '0'))
        except ValueError:
            count = 0

        questions = []
        if subject and level and count > 0:
            try:
                questions = generate_mcqs(subject, level, count)
            except Exception as e:
                print(f"Error generating main exam questions: {e}")

        # Option B: Custom JSON (overrides Option A if provided and valid)
        custom_json = request.form.get('custom_questions_json', '').strip()
        if custom_json:
            try:
                parsed = json.loads(custom_json)
                if isinstance(parsed, list):
                    # Validate minimal schema
                    valid_list = []
                    for item in parsed:
                        if isinstance(item, dict) and all(k in item for k in ["question", "options", "correct_answer"]):
                            valid_list.append(item)
                    if valid_list:
                        questions = valid_list
            except Exception as e:
                print(f"Invalid custom questions JSON: {e}")

        active = request.form.get('active') == 'on'

        # Access control: mode all/selected and list of usernames
        access_mode = request.form.get('access_mode', 'all')
        # Prefer checkbox selections
        allowed_usernames = request.form.getlist('allowed_usernames') or []
        # Fallback: textarea comma-separated list if present
        if not allowed_usernames:
            raw_user_list = request.form.get('allowed_users', '').strip()
            if access_mode == 'selected' and raw_user_list:
                allowed_usernames = [u.strip() for u in raw_user_list.split(',') if u.strip()]

        # Reset attempts for targeted users
        # Reset attempts: from checkboxes and/or textarea
        reset_names = request.form.getlist('reset_usernames') or []
        reset_field = request.form.get('reset_attempts', '').strip()
        if reset_field:
            reset_names += [u.strip() for u in reset_field.split(',') if u.strip()]
        if reset_names:
            users = load_users()
            changed = False
            for uname in reset_names:
                if uname in users and users[uname].get('main_exam_attempted'):
                    users[uname]['main_exam_attempted'] = False
                    changed = True
            if changed:
                save_users(users)
                flash('Selected users can re-attempt the main exam.', 'success')

        new_config = {
            'active': active,
            'duration_minutes': max(0, duration_minutes),
            'questions': questions or current_config.get('questions', []),
            'access': {
                'mode': access_mode,
                'user_ids': allowed_usernames
            }
        }
        save_main_exam(new_config)

        # If requested, reset attempts for the newly allowed users now
        if request.form.get('reset_allowed_now') == 'on' and access_mode == 'selected' and allowed_usernames:
            users = load_users()
            changed = False
            for uname in allowed_usernames:
                if uname in users and users[uname].get('main_exam_attempted'):
                    users[uname]['main_exam_attempted'] = False
                    changed = True
            if changed:
                save_users(users)
                flash('Re-attempts enabled for selected users.', 'success')
        flash('Main exam configuration saved.', 'success')
        return redirect(url_for('admin_main_exam'))

    # Provide usernames list to help admin
    users = load_users()
    all_usernames = sorted(list(users.keys()))
    return render_template('admin_main_exam.html', config=current_config, all_usernames=all_usernames)


# --------- USER: Start and Take Main Exam with Timer ---------
@app.route('/main_exam/start')
@login_required
def main_exam_start():
    # Load configured exam
    config = load_main_exam()
    if not config.get('active'):
        flash('Main exam is not active.', 'warning')
        return redirect(url_for('index'))

    # Ensure questions exist
    questions = config.get('questions', [])
    if not questions:
        flash('Main exam has no questions configured.', 'danger')
        return redirect(url_for('index'))

    # Enforce access control and single attempt per user
    users = load_users()
    username = session.get('username')
    access = config.get('access', {"mode": "all", "user_ids": []})
    if access.get('mode') == 'selected' and (not username or username not in access.get('user_ids', [])):
        flash('You are not allowed to take the main exam.', 'danger')
        return redirect(url_for('index'))
    if username and users.get(username, {}).get('main_exam_attempted'):
        flash('You have already attempted the main exam.', 'info')
        return redirect(url_for('index'))

    # Initialize session for main exam
    session['main_exam_questions'] = questions
    session['main_exam_user_selections'] = [None] * len(questions)
    duration_minutes = int(config.get('duration_minutes', 0) or 0)
    session['main_exam_end_time'] = (datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)).isoformat()
    return redirect(url_for('main_exam'))


@app.route('/main_exam', methods=['GET', 'POST'])
@login_required
def main_exam():
    questions = session.get('main_exam_questions')
    end_time_iso = session.get('main_exam_end_time')
    if not questions or not end_time_iso:
        flash('Main exam session not started.', 'warning')
        return redirect(url_for('index'))

    # Remaining time enforcement
    try:
        end_time = datetime.datetime.fromisoformat(end_time_iso)
    except Exception:
        end_time = datetime.datetime.utcnow()
    remaining_seconds = max(0, int((end_time - datetime.datetime.utcnow()).total_seconds()))

    user_selections = session.get('main_exam_user_selections', [None] * len(questions))
    if len(user_selections) != len(questions):
        user_selections = [None] * len(questions)
        session['main_exam_user_selections'] = user_selections

    if request.method == 'POST' or remaining_seconds == 0:
        current_answers = []
        all_answered = True
        new_selections_from_form = [None] * len(questions)

        for i, q_data in enumerate(questions):
            selected_number = request.form.get(f'q_{i}') if request.method == 'POST' else None
            options = q_data['options']
            selected_option = None
            valid = True

            if selected_number is None or str(selected_number).strip() == '':
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
            
            # Correctly indented code for each question in the loop
            is_correct = (selected_option == q_data['correct_answer']) if valid else False

            current_answers.append({
                "question": q_data['question'],
                "options": q_data['options'],
                "user_answer": selected_option if valid else selected_number,
                "correct_answer": q_data['correct_answer'],
                "is_correct": is_correct,
                "answer_number": selected_number
            })

        session['main_exam_user_selections'] = new_selections_from_form

        # Finalize submission either on manual submit or timeout
        full_submission_data = {
            "user_info": session['user_info'],
            "exam_type": "main_exam",
            "questions_generated": [q['question'] for q in questions],
            "answers": current_answers,
            "timestamp": datetime.datetime.now().isoformat()
        }
        pdf_path = create_pdf_report(full_submission_data)
        full_submission_data["report_file"] = os.path.basename(pdf_path)
        save_submission(full_submission_data)

        # Mark user as attempted
        users = load_users()
        username = session.get('username')
        if username in users:
            users[username]['main_exam_attempted'] = True
            save_users(users)

        # Cleanup and redirect to report
        session['last_pdf_path'] = pdf_path
        session['submission_complete'] = True
        session.pop('main_exam_questions', None)
        session.pop('main_exam_user_selections', None)
        session.pop('main_exam_end_time', None)
        flash('Main exam submitted!', 'success')
        return redirect(url_for('report_display'))

    return render_template('main_exam.html', questions=questions, user_info=session.get('user_info', {}), user_selections=user_selections, remaining_seconds=remaining_seconds)
    
@app.route('/report')
@login_required
def report_display():
    # Show a list of past submissions for the logged-in user
    username = session.get('username')
    if not username:
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))

    submissions = load_submissions()
    user_subs = []
    for sub in submissions:
        # match by name+phone or unique_id if available
        u = sub.get('user_info', {})
        if not u:
            continue
        if session.get('user_info', {}).get('unique_id') and u.get('unique_id') == session['user_info']['unique_id']:
            user_subs.append(sub)
        elif session.get('user_info', {}).get('name') == u.get('name') and session.get('user_info', {}).get('phone') == u.get('phone'):
            user_subs.append(sub)

    # Sort newest first
    try:
        user_subs.sort(key=lambda s: s.get('timestamp', ''), reverse=True)
    except Exception:
        pass

    return render_template('report.html', submissions=user_subs)

@app.route('/download_report/<path:filename>')
@login_required
def download_report(filename):
    safe_path = os.path.join(REPORTS_DIR, filename)
    if os.path.exists(safe_path):
        return send_file(safe_path, as_attachment=True)
    else:
        flash("Report file not found.", 'danger')
        return redirect(url_for('report_display'))

@app.route('/start_new_quiz')
@login_required
def start_new_quiz():
    session.pop('questions', None)
    session.pop('user_selections', None)
    session.pop('submission_complete', None)
    session.pop('last_pdf_path', None)
    flash("You can now start a new quiz.", 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Create necessary files if they don't exist
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(SUBMISSIONS_FILE):
        with open(SUBMISSIONS_FILE, 'w') as f:
            json.dump([], f)
    # Ensure the question bank file exists
    if not os.path.exists(QUESTION_BANK_FILE):
        with open(QUESTION_BANK_FILE, 'w') as f:
            json.dump([], f) # Initialize as an empty list

    # Ensure main exam file exists
    if not os.path.exists(MAIN_EXAM_FILE):
        with open(MAIN_EXAM_FILE, 'w') as f:
            json.dump({"active": False, "duration_minutes": 0, "questions": []}, f)

    # Create 'fonts' directory if it doesn't exist
    if not os.path.exists('fonts'):
        os.makedirs('fonts')

    # Ensure reports directory exists
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

    app.run(debug=True)