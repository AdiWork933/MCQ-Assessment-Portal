# Required Library
import os
import streamlit as st
import json
from dotenv import load_dotenv
import google.generativeai as genai
from fpdf import FPDF

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Define the JSON file path for submissions
SUBMISSIONS_FILE = "submissions.json"

# -------------- UTILITY FUNCTIONS --------------

def generate_mcqs(subject, level, count):
    """
    Generates multiple-choice questions using the Gemini API.

    Args:
        subject (str): The subject for the MCQs.
        level (str): The difficulty level of the MCQs.
        count (int): The number of MCQs to generate.

    Returns:
        str: The raw text response from the Gemini model.
    """
    prompt = f"""
    Generate {count} multiple choice questions (MCQs) for the subject '{subject}' at the '{level}' difficulty level.
    Provide 4 options for each question and indicate the correct answer clearly.

    Format:
    Q: Question text
    Options: [A] option1 [B] option2 [C] option3 [D] option4
    Answer: B
    """
    model = genai.GenerativeModel(model_name="models/gemini-2.0-flash")
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Error generating questions: {e}")
        return ""

def parse_mcqs(raw_text):
    """
    Parses the raw text response from the Gemini model into a structured list of questions.

    Args:
        raw_text (str): The raw text containing MCQs.

    Returns:
        list: A list of tuples, where each tuple contains (question, options_list, correct_answer_text).
    """
    lines = raw_text.splitlines()
    questions = []
    q, opts, ans = None, [], None
    for line in lines:
        line = line.strip() # Strip whitespace from the line
        if line.startswith("Q:"):
            # If a previous question was incomplete, reset
            if q and opts:
                st.warning(f"Skipping incomplete question data: Q='{q}', Options='{opts}'")
            q = line[2:].strip()
            opts = []
            ans = None
        elif line.startswith("Options:"):
            # Extract options from the "Options:" line
            options_str = line[8:].strip()
            # Split by common delimiters like '[A]', '[B]', etc., while keeping the option text
            temp_opts = [o.strip() for o in options_str.split('[') if o.strip()]
            opts = []
            for item in temp_opts:
                if ']' in item:
                    # Extract the option text after the bracket, e.g., 'A] option' -> 'option'
                    opts.append(item.split(']', 1)[1].strip())
        elif line.startswith("Answer:"):
            ans_letter = line.split(":")[-1].strip().upper()
            correct_index = {"A": 0, "B": 1, "C": 2, "D": 3}.get(ans_letter, None)
            
            # Ensure all parts are valid before adding the question
            if q and opts and correct_index is not None and 0 <= correct_index < len(opts):
                questions.append((q, opts, opts[correct_index])) # Store question, all options, and correct answer text
            else:
                st.warning(f"Failed to parse question: Q='{q}', Options='{opts}', Answer Letter='{ans_letter}'")
            # Reset for the next question
            q, opts, ans = None, [], None
    return questions

def create_pdf_report(submission_data, filename=None):
    """
    Creates a PDF report for a single submission.

    Args:
        submission_data (dict): A dictionary containing 'user_info' and 'answers' for one submission.
        filename (str, optional): The desired filename for the PDF. Defaults to None.

    Returns:
        str: The path to the generated PDF file.
    """
    user_info = submission_data.get('user_info', {})
    answers_data = submission_data.get('answers', [])

    name_cleaned = user_info.get('name', 'candidate').replace(" ", "_").lower()
    if filename is None:
        filename = f"{name_cleaned}_report.pdf" # Removed date as requested

    # Calculate score
    total_questions = len(answers_data)
    correct_count = sum(1 for ans_item in answers_data if ans_item.get('is_correct', False))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Report Card Header
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt="MCQ Submission Report", ln=True, align="C")
    pdf.ln(5)

    # Candidate Information
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, txt="Candidate Information:", ln=True)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 7, txt=f"Name: {user_info.get('name', 'N/A')}", ln=True)
    pdf.cell(0, 7, txt=f"Stream: {user_info.get('stream', 'N/A')}", ln=True)
    pdf.cell(0, 7, txt=f"Phone: {user_info.get('phone', 'N/A')}", ln=True)
    pdf.ln(5)

    # Summary
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, txt="Results Summary:", ln=True)
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 7, txt=f"Total Questions: {total_questions}", ln=True)
    pdf.cell(0, 7, txt=f"Correct Answers: {correct_count}", ln=True)
    pdf.cell(0, 7, txt=f"Score: {correct_count}/{total_questions}", ln=True)
    pdf.ln(10)

    # Detailed Answers
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, txt="Detailed Answers:", ln=True)
    pdf.set_font("Arial", '', 10) # Smaller font for details

    for idx, ans_item in enumerate(answers_data, 1):
        question_text = ans_item.get('question', 'N/A')
        user_answer = ans_item.get('user_answer', 'Not answered')
        correct_answer = ans_item.get('correct_answer', 'N/A')
        is_correct = ans_item.get('is_correct', False)

        result_text = "Correct" if is_correct else "Incorrect"
        result_color = (0, 128, 0) if is_correct else (255, 0, 0) # Green for correct, Red for incorrect

        # Removed 'ln=True' from multi_cell calls
        pdf.set_fill_color(240, 240, 240) # Light grey background for each question block
        pdf.multi_cell(0, 7, f"Q{idx}: {question_text}", border=1, align='L', fill=True)
        pdf.multi_cell(0, 7, f"Your Answer: {user_answer}", border=1, align='L', fill=True)
        pdf.multi_cell(0, 7, f"Correct Answer: {correct_answer}", border=1, align='L', fill=True)
        pdf.set_text_color(*result_color) # Apply color
        pdf.multi_cell(0, 7, f"Result: {result_text}", border=1, align='L', fill=True)
        pdf.set_text_color(0, 0, 0) # Reset color to black
        pdf.ln(5) # Add a small break between questions

    pdf.output(filename)
    return filename

def load_submissions():
    """Loads existing submissions from the JSON file."""
    if os.path.exists(SUBMISSIONS_FILE):
        try:
            with open(SUBMISSIONS_FILE, "r") as f:
                content = f.read().strip()
                if content: # Check if file is not empty
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
                    else: # If it's a single object, convert it to a list
                        return [data]
                else:
                    return [] # File is empty
        except json.JSONDecodeError:
            st.error("Error decoding JSON file. Starting with an empty list.")
            return []
    return []

def save_submission(submission_data):
    """Appends a new submission to the JSON file."""
    all_submissions = load_submissions()
    all_submissions.append(submission_data)
    with open(SUBMISSIONS_FILE, "w") as f:
        json.dump(all_submissions, f, indent=2)

# ----------------- UI -----------------

def main():
    st.set_page_config(page_title="MCQ Portal", layout="centered")
    st.title("📚 Gemini-based MCQ Submission Portal")

    # Initialize session state for navigation
    if 'page' not in st.session_state:
        st.session_state.page = 'user_info_entry'
    if 'user_info' not in st.session_state:
        st.session_state.user_info = {"name": "", "stream": "", "phone": ""}
    if 'questions' not in st.session_state:
        st.session_state.questions = []
    if 'answers_submitted' not in st.session_state:
        st.session_state.answers_submitted = False

    # --- Page 1: User Information Entry ---
    if st.session_state.page == 'user_info_entry':
        st.subheader("Enter Candidate Information:")
        
        # Pre-fill inputs if data exists in session state
        name = st.text_input("Name", value=st.session_state.user_info.get('name', ''))
        stream = st.text_input("Stream", value=st.session_state.user_info.get('stream', ''))
        phone = st.text_input("Phone Number", value=st.session_state.user_info.get('phone', ''))

        if st.button("Save Candidate Info & Proceed to MCQs"):
            if not name or not stream or not phone:
                st.warning("Please fill in all candidate details.")
            else:
                st.session_state.user_info = {"name": name, "stream": stream, "phone": phone}
                st.session_state.page = 'mcq_generation'
                st.rerun() # Rerun to switch to the next page

    # --- Page 2: MCQ Generation ---
    if st.session_state.page == 'mcq_generation':
        st.subheader("Generate MCQs")

        st.write(f"Candidate: **{st.session_state.user_info['name']}**")
        subject = st.text_input("Enter Subject", key="subject_gen")
        level = st.selectbox("Select Difficulty Level", ["Simple", "Intermediate", "Hard", "Fire"], key="level_gen")
        count = st.slider("Number of MCQs", 1, 10, 3, key="count_gen")

        if st.button("Generate MCQs"):
            if not subject:
                st.warning("Please enter a subject to generate questions.")
            else:
                with st.spinner("Generating questions from Gemini..."):
                    raw = generate_mcqs(subject, level, count)
                    questions = parse_mcqs(raw)
                    if questions:
                        st.session_state.questions = questions
                        # Reset user_selections here to match the new number of questions
                        st.session_state.user_selections = [None] * len(questions) 
                        st.session_state.answers_submitted = False # Reset submission status
                        st.session_state.page = 'mcq_answering' # Move to answering page
                        st.rerun()
                    else:
                        st.error("Failed to generate valid MCQs. Try again.")

    # --- Page 3: MCQ Answering ---
    if st.session_state.page == 'mcq_answering' and st.session_state.questions:
        st.subheader("Answer the following questions:")
        st.write(f"Candidate: **{st.session_state.user_info['name']}**")

        current_answers = []
        # Ensure user_selections is correctly sized for the current questions
        if len(st.session_state.user_selections) != len(st.session_state.questions):
            st.session_state.user_selections = [None] * len(st.session_state.questions)

        for i, (question_text, options_list, correct_answer_text) in enumerate(st.session_state.questions):
            st.write(f"**Q{i+1}: {question_text}**")
            
            # Create a unique key for each radio button group
            radio_key = f"ans_{i}"
            
            # Use a dummy first option to ensure nothing is selected by default and user has to actively choose
            options_for_radio = ["-- Select an option --"] + options_list
            
            # Get current selection for this question, or default to the placeholder
            current_selection_value = st.session_state.user_selections[i]
            
            # Find the index of the current_selection_value in options_for_radio
            try:
                default_index = options_for_radio.index(current_selection_value)
            except ValueError:
                default_index = 0 # Default to '-- Select an option --' if not found

            selected_option = st.radio(
                "Choose an option:",
                options_for_radio,
                index=default_index,
                key=radio_key
            )
            
            # Update user_selections in session state
            if selected_option != "-- Select an option --":
                st.session_state.user_selections[i] = selected_option
            else:
                st.session_state.user_selections[i] = None

            # Prepare data for submission
            is_correct = (selected_option == correct_answer_text)
            current_answers.append({
                "question": question_text,
                "options": options_list,
                "user_answer": selected_option if selected_option != "-- Select an option --" else None,
                "correct_answer": correct_answer_text,
                "is_correct": is_correct if selected_option != "-- Select an option --" else False # Mark as false if not answered
            })

        if st.button("Submit Answers"):
            # Check if all questions have been answered (not just the placeholder)
            if any(ans["user_answer"] is None for ans in current_answers):
                st.warning("Please answer all questions before submitting.")
            else:
                with st.spinner("Processing your submission..."):
                    # Compile all data for the current submission
                    full_submission_data = {
                        "user_info": st.session_state.user_info,
                        "questions_generated": [q[0] for q in st.session_state.questions], # Store just the questions text
                        "answers": current_answers
                    }
                    
                    save_submission(full_submission_data) # Append to JSON
                    pdf_path = create_pdf_report(full_submission_data) # Create PDF for this submission

                    st.success("Your answers have been submitted and saved!")
                    with open(pdf_path, "rb") as f:
                        st.download_button("📄 Download Report Card", f, file_name=pdf_path, mime="application/pdf")
                    
                    st.session_state.answers_submitted = True
                    st.session_state.page = 'report_display' # Move to report display page
                    st.session_state.last_pdf_path = pdf_path # Store path for immediate download
                    st.rerun() # Rerun to show report section

    # --- Page 4: Report Display (after submission) ---
    if st.session_state.page == 'report_display' and st.session_state.answers_submitted:
        st.subheader("Submission Complete!")
        st.success("Your report card has been generated and saved.")
        
        # Provide download button again if page reloads without showing it
        if st.session_state.get('last_pdf_path') and os.path.exists(st.session_state.last_pdf_path):
             with open(st.session_state.last_pdf_path, "rb") as f:
                st.download_button("📄 Download Report Card Again", f, file_name=os.path.basename(st.session_state.last_pdf_path), mime="application/pdf")

        st.markdown("---")
        st.write("You can now:")
        if st.button("Start a New Quiz"):
            # Reset relevant session states for a new quiz
            st.session_state.page = 'user_info_entry'
            st.session_state.questions = []
            st.session_state.answers_submitted = False
            st.session_state.user_selections = []
            st.session_state.user_info = {"name": "", "stream": "", "phone": ""} # Clear user info for a fresh start
            st.rerun()

        # You can optionally display the last submitted answers or a summary here
        # For brevity, this example just provides the download and restart button.

if __name__ == "__main__":
    main()
