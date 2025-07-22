# 🚀 MCQ Assessment Portal V2

## 📘 Project Description

This is a **Flask-based web application** that delivers an advanced, AI-powered **Multiple Choice Question (MCQ) assessment portal**. The portal dynamically generates MCQs using the **Google Gemini API**, allowing users to take quizzes based on their selected subjects, difficulty levels, and desired number of questions.

Built with **Python, Flask, HTML, and CSS**, the platform is now designed for **scalability, multi-user access, and real-time result analysis**. Users can log in, attempt quizzes, and download detailed **PDF reports**, while administrators can manage the system from a secure backend dashboard.

---

## 💡 Use Cases

- **🎓 Educational Institutions** – Automate quizzes for various subjects and track student performance.
- **🏢 Corporate Training** – Create adaptive assessments for employee upskilling and onboarding.
- **📚 Self-Assessment** – Students can practice custom quizzes for revision and preparation.
- **🧠 Interview Preparation** – Helps candidates and recruiters simulate knowledge-based assessments.

---

## 🚀 Features

- 🔐 **Login / Signup System**  
  Secure user authentication with password encryption and validation.

- 🧾 **Main Dashboard**  
  Displays personalized options like starting exams, viewing results, and accessing reports.

- 🧠 **Dynamic Exam Page**  
  Generates MCQs using Google Gemini API based on subject and difficulty; interactive UI for answering.

- 📊 **Result View Page**  
  Users can instantly see their quiz score, performance breakdown, and correct answers.

- 📄 **PDF Report Generation**  
  Auto-generated result cards available for download, summarizing the user’s attempt.

- 📁 **Persistent Question Bank**  
  Stores previously generated questions to reduce API usage and build a growing knowledge base.

- 👨‍💼 **Admin Dashboard**  
  Role-based access for admins to manage users, view submissions, and monitor platform activity.

- 🔁 **Forget Password Page**  
  Password recovery flow via email (or OTP), enabling smooth user experience.

- 🧪 **Multi-User Support**  
  Built to handle multiple users concurrently with personalized sessions and access levels.

---

## 🛠️ Tech Stack

- **Backend:** Python, Flask  
- **Frontend:** HTML, CSS, Bootstrap  
- **AI Model:** Google Gemini API (`gemini-2.0-flash`)  
- **Database:** JSON-based storage (or can be extended to use SQL)  
- **Report Generation:** PDFKit / ReportLab  
- **Deployment-ready**

---

## 📷 UI Snapshots

<table>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/dcdcdbfe-4b79-4219-8458-05bb62fdfdd1" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/43d7d2a5-5e41-433e-8909-e14dc258f1f8" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/8f5e2516-34e1-4cf1-b295-4fa3fe6eaf91" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/b69cf2ca-be67-4780-858d-1a371746db02" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/31cc15ec-074a-4034-8c87-9ebaa805190b" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/19c8fb9b-7242-4d7a-a066-3eca045523b7" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/cf067197-ef50-45ba-a0d2-bd8f15d14ad5" width="100%"/></td>
    <td><img src="https://github.com/user-attachments/assets/1dcb9446-0c4f-4a4d-9d59-2e5accc94807" width="100%"/></td>
  </tr>
</table>

---

## ✅ Prerequisites

- Python 3.8 or higher  
- Google API Key with access to `gemini-2.0-flash`  
- Flask  
- PDFKit or ReportLab for PDF generation  
- Bootstrap for UI styling (optional but recommended)

---

## 📦 Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/mcq-assessment-portal-v2.git
cd mcq-assessment-portal-v2
```
