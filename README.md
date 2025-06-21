# MCQ Assessment Portal

## 📘 Project Description

This is a **Streamlit-based web application** that serves as an interactive **Multiple Choice Question (MCQ) assessment portal**. It leverages the **Google Gemini API** to dynamically generate MCQs based on user-defined subjects, difficulty levels, and counts. Users can submit their candidate information, answer the generated questions, and receive an **instant report card in PDF format**. All submission data is persistently stored in a `submissions.json` file.

---

## 💡 Use Cases

- **Educational Institutions**: Automate quizzes for students based on custom subjects and difficulty levels.
- **Corporate Training**: Quickly generate assessments for employees in training sessions.
- **Self-Assessment**: Students or learners can generate and practice custom quizzes for revision.
- **Interview Preparation**: Tech recruiters or candidates can simulate objective-based assessments.

---

## 🚀 Features

- **Dynamic MCQ Generation**  
  Generate multiple-choice questions on various subjects and difficulty levels using the Gemini API.

- **Multi-Page User Flow**  
  Guides users through: candidate info → MCQ generation → answering → report display.

- **Candidate Information Capture**  
  Collects essential details like name, stream, and phone number.

- **Interactive Quiz Interface**  
  Presents MCQs with radio-button answers.

- **Instant Report Card**  
  Generates a personalized PDF report with correct/incorrect answers and scores.

- **Data Persistence**  
  Saves all data (candidate info, questions, answers, results) in `submissions.json`.

- **Downloadable Reports**  
  Users can download their PDF report card.

- **Responsive Design**  
  Built with Streamlit for a smooth experience across devices.

---

## 🛠️ Setup Instructions

### ✅ Prerequisites

- Python 3.8 or higher  
- Google API Key with access to the `gemini-2.0-flash` model

---

### 📦 1. Clone the Repository (or create `app.py`)

```bash
# If you need to create a new directory and file
mkdir mcq_portal
cd mcq_portal
# Create app.py and paste the provided code into it
