from flask import Flask, jsonify, render_template, request, redirect, session
from PIL import Image, ImageDraw, ImageFont
import mysql.connector
import qrcode
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---------------- CREATE REQUIRED FOLDERS ----------------
os.makedirs("static/photos", exist_ok=True)
os.makedirs("static/qr", exist_ok=True)
os.makedirs("static/id_cards", exist_ok=True)
os.makedirs("static/videos", exist_ok=True)

# ---------------- DATABASE CONNECTION ----------------
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="phani60",
    database="lms_db"
)

# ================= EMAIL FUNCTION =================
def send_email_with_attachments(to_email, subject, body, files):
    EMAIL_ADDRESS = "kuretiphaneendra@gmail.com"
    EMAIL_PASSWORD = "rokpmozraaesshrw"

    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    for file_path in files:
        with open(file_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="image",
                subtype="png",
                filename=os.path.basename(file_path)
            )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

# ================= ID CARD GENERATOR =================
def generate_id_card(name, roll, photo_path, qr_path):
    WIDTH, HEIGHT = 400, 600
    card = Image.new("RGB", (WIDTH, HEIGHT), "#F2F2F2")
    draw = ImageDraw.Draw(card)

    try:
        title_font = ImageFont.truetype("arial.ttf", 22)
        name_font = ImageFont.truetype("arial.ttf", 20)
        role_font = ImageFont.truetype("arial.ttf", 16)
    except:
        title_font = name_font = role_font = ImageFont.load_default()

    draw.rectangle((0, 0, WIDTH, 110), fill="#E85C50")
    draw.text((WIDTH//2 - 100, 40), "YOUR COLLEGE NAME", fill="white", font=title_font)

    photo = Image.open(photo_path).resize((150, 170))
    card.paste(photo, (WIDTH//2 - 75, 130))

    draw.text((WIDTH//2 - 80, 330), name, fill="#222", font=name_font)
    draw.text((WIDTH//2 - 40, 360), "STUDENT", fill="#555", font=role_font)
    draw.text((WIDTH//2 - 70, 395), f"Roll No : {roll}", fill="#222", font=role_font)

    qr = Image.open(qr_path).resize((140, 140))
    card.paste(qr, (WIDTH//2 - 70, 430))

    id_path = f"static/id_cards/{roll}_id.png"
    card.save(id_path)
    return id_path

# ================= ROUTES =================
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/student-register")
def student_register_page():
    return render_template("student_register.html")

@app.route("/teacher-register")
def teacher_register_page():
    return render_template("teacher_register.html")

# ================= STUDENT REGISTRATION =================
@app.route("/register-student", methods=["POST"])
def register_student():
    name = request.form["name"]
    roll = request.form["roll"]
    email = request.form["email"]
    parent_email = request.form["parent_email"]

    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE roll=%s", (roll,))
    if cursor.fetchone():
        return "<h3>Student already exists!</h3>"

    # Set QR expiry for 1 year
    expiry_date = datetime.now().date() + timedelta(days=365)

    photo = request.files["photo"]
    photo_path = f"static/photos/{roll}.png"
    photo.save(photo_path)

    student_qr_path = f"static/qr/student_{roll}.png"
    qrcode.make(f"role=student&roll={roll}").save(student_qr_path)

    id_card_path = generate_id_card(name, roll, photo_path, student_qr_path)

    # Insert student with expiry
    cursor.execute("""
        INSERT INTO users 
        (name, roll, email, role, photo, qr_code, qr_expiry_date)
        VALUES (%s,%s,%s,'student',%s,%s,%s)
    """, (name, roll, email, photo_path, student_qr_path, expiry_date))

    parent_qr_path = f"static/qr/parent_{roll}.png"
    qrcode.make(f"role=parent&roll={roll}").save(parent_qr_path)

    # Insert parent with expiry
    cursor.execute("""
        INSERT INTO users 
        (name, email, role, qr_code, linked_student_roll, qr_expiry_date)
        VALUES (%s,%s,'parent',%s,%s,%s)
    """, (f"Parent of {roll}", parent_email, parent_qr_path, roll, expiry_date))

    db.commit()

    send_email_with_attachments(email, "Student ID Card", "Your ID attached.", [id_card_path])
    send_email_with_attachments(parent_email, "Parent QR", "Scan QR to access dashboard.", [parent_qr_path])

    return "<h3>Student Registered Successfully</h3>"

# ================= TEACHER REGISTRATION =================
@app.route("/register-teacher", methods=["POST"])
def register_teacher():
    name = request.form["name"]
    email = request.form["email"]

    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE email=%s AND role='teacher'", (email,))
    if cursor.fetchone():
        return "<h3>Teacher already exists!</h3>"

    teacher_qr_path = f"static/qr/teacher_{email}.png"
    qrcode.make(f"role=teacher&email={email}").save(teacher_qr_path)

    cursor.execute("""
        INSERT INTO users (name, email, role, qr_code)
        VALUES (%s,%s,'teacher',%s)
    """, (name, email, teacher_qr_path))

    db.commit()

    send_email_with_attachments(email, "Teacher QR Login", "Scan to login.", [teacher_qr_path])

    return "<h3>Teacher Registered Successfully</h3>"

# ================= QR LOGIN =================
@app.route("/qr-login", methods=["POST"])
def qr_login():
    data = request.get_json()
    qr_data = data.get("qr_data")

    parts = dict(item.split("=", 1) for item in qr_data.split("&"))

    role = parts.get("role")
    roll = parts.get("roll")
    email = parts.get("email")

    cursor = db.cursor(dictionary=True)

    # ================= STUDENT LOGIN =================
    if role == "student":
        cursor.execute("""
            SELECT qr_expiry_date FROM users
            WHERE roll=%s AND role='student'
        """, (roll,))
        user = cursor.fetchone()

        if user and user["qr_expiry_date"] and user["qr_expiry_date"] >= datetime.now().date():
            return jsonify({"redirect": f"/student-dashboard/{roll}"})
        else:
            return jsonify({"error": "Student QR Code Expired"})

    # ================= PARENT LOGIN =================
    if role == "parent":
        cursor.execute("""
            SELECT qr_expiry_date FROM users
            WHERE linked_student_roll=%s AND role='parent'
        """, (roll,))
        user = cursor.fetchone()

        if user and user["qr_expiry_date"] and user["qr_expiry_date"] >= datetime.now().date():
            return jsonify({"redirect": f"/parent-dashboard/{roll}"})
        else:
            return jsonify({"error": "Parent QR Code Expired"})

    # ================= TEACHER LOGIN =================
    if role == "teacher":
        cursor.execute("""
            SELECT * FROM users 
            WHERE role='teacher' AND email=%s
        """, (email,))
        teacher = cursor.fetchone()

        if teacher:
            session["teacher_email"] = email
            return jsonify({"redirect": "/teacher-dashboard"})

    return jsonify({"error": "Unauthorized QR"})

# ================= TEACHER DASHBOARD =================
@app.route("/teacher-dashboard")
def teacher_dashboard():
    if "teacher_email" not in session:
        return "<h3>Access Denied</h3>"

    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM domains")
    domains = cursor.fetchall()

    cursor.execute("""
        SELECT lectures.*, domains.name as domain_name
        FROM lectures
        JOIN domains ON lectures.domain_id = domains.id
        WHERE uploaded_by=%s
        ORDER BY upload_date DESC
    """, (session["teacher_email"],))

    lectures = cursor.fetchall()

    return render_template("teacher_dashboard.html",
                           lectures=lectures,
                           domains=domains)
# ================= UPLOAD LECTURE =================
@app.route("/upload-lecture", methods=["POST"])
def upload_lecture():
    if "teacher_email" not in session:
        return "<h3>Unauthorized</h3>"

    title = request.form["title"]
    description = request.form["description"]
    domain_id = request.form["domain_id"]

    video = request.files["video"]
    video_path = f"static/videos/{video.filename}"
    video.save(video_path)

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO lectures (title, description, video_path, uploaded_by, domain_id)
        VALUES (%s,%s,%s,%s,%s)
    """, (title, description, video_path, session["teacher_email"], domain_id))

    db.commit()

    return redirect("/teacher-dashboard")
@app.route("/teacher-logout")
def teacher_logout():
    session.pop("teacher_email", None)
    return redirect("/login")

@app.route("/create-exam", methods=["POST"])
def create_exam():
    if "teacher_email" not in session:
        return "<h3>Unauthorized</h3>"

    title = request.form["title"]
    total_marks = request.form["total_marks"]
    exam_date = request.form["exam_date"]

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO exams (title, total_marks, exam_date, created_by)
        VALUES (%s,%s,%s,%s)
    """, (title, total_marks, exam_date, session["teacher_email"]))

    db.commit()
    return redirect("/teacher-dashboard")
@app.route("/add-marks", methods=["POST"])
def add_marks():
    if "teacher_email" not in session:
        return "<h3>Unauthorized</h3>"

    roll = request.form["roll"]
    exam_id = request.form["exam_id"]
    score = request.form["score"]

    cursor = db.cursor(dictionary=True)

    # Get student user_id
    cursor.execute("SELECT id FROM users WHERE roll=%s AND role='student'", (roll,))
    student = cursor.fetchone()

    if not student:
        return "Student not found"

    user_id = student["id"]

    cursor.execute("""
        INSERT INTO exam_results (user_id, exam_id, score)
        VALUES (%s,%s,%s)
    """, (user_id, exam_id, score))

    db.commit()
    return redirect("/teacher-dashboard")
@app.route("/mark-attendance", methods=["POST"])
def mark_attendance():
    if "teacher_email" not in session:
        return "<h3>Unauthorized</h3>"

    roll = request.form["roll"]
    date = request.form["date"]
    status = request.form["status"]

    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id FROM users WHERE roll=%s AND role='student'", (roll,))
    student = cursor.fetchone()

    if not student:
        return "Student not found"

    user_id = student["id"]

    cursor.execute("""
        INSERT INTO attendance (user_id, date, status)
        VALUES (%s,%s,%s)
    """, (user_id, date, status))

    db.commit()
    return redirect("/teacher-dashboard")

# ================= STUDENT DASHBOARD =================
# ================= STUDENT DASHBOARD =================
@app.route("/student-dashboard/<roll>")
def student_dashboard(roll):
    cursor = db.cursor(dictionary=True)

    # Get selected domain from URL (for filtering)
    domain_id = request.args.get("domain")

    # Fetch all domains for dropdown
    cursor.execute("SELECT * FROM domains")
    domains = cursor.fetchall()

    # If domain selected → filter
    if domain_id:
        cursor.execute("""
            SELECT lectures.*, domains.name as domain_name
            FROM lectures
            JOIN domains ON lectures.domain_id = domains.id
            WHERE lectures.domain_id = %s
            ORDER BY upload_date DESC
        """, (domain_id,))
    else:
        cursor.execute("""
            SELECT lectures.*, domains.name as domain_name
            FROM lectures
            JOIN domains ON lectures.domain_id = domains.id
            ORDER BY upload_date DESC
        """)

    lectures = cursor.fetchall()

    return render_template(
        "student_dashboard.html",
        roll=roll,
        lectures=lectures,
        domains=domains
    )
# ================= PARENT DASHBOARD =================
@app.route("/parent-dashboard/<roll>")
def parent_dashboard(roll):
    cursor = db.cursor(dictionary=True)

    # Get student details
    cursor.execute("SELECT id, name, roll FROM users WHERE roll=%s AND role='student'", (roll,))
    student = cursor.fetchone()

    if not student:
        return "Student not found"

    user_id = student["id"]

    # Get exam results
    cursor.execute("""
        SELECT exams.title, exams.total_marks, exam_results.score
        FROM exam_results
        JOIN exams ON exam_results.exam_id = exams.id
        WHERE exam_results.user_id = %s
    """, (user_id,))
    results = cursor.fetchall()

    # Calculate Grade for each exam
    for r in results:
        if r["total_marks"] and r["total_marks"] != 0:
            percentage = (r["score"] / r["total_marks"]) * 100
            r["percentage"] = round(percentage, 2)

            if percentage >= 90:
                r["grade"] = "A+"
            elif percentage >= 75:
                r["grade"] = "A"
            elif percentage >= 60:
                r["grade"] = "B"
            elif percentage >= 50:
                r["grade"] = "C"
            else:
                r["grade"] = "Fail"
        else:
            r["percentage"] = 0
            r["grade"] = "-"

    # Get attendance
    cursor.execute("""
        SELECT date, status
        FROM attendance
        WHERE user_id=%s
    """, (user_id,))
    attendance = cursor.fetchall()

    # Calculate Attendance Percentage
    total_days = len(attendance)
    present_days = sum(1 for a in attendance if a["status"] == "Present")

    attendance_percentage = 0
    if total_days > 0:
        attendance_percentage = round((present_days / total_days) * 100, 2)

    return render_template(
        "parent_dashboard.html",
        student=student,
        results=results,
        attendance=attendance,
        attendance_percentage=attendance_percentage
    )
# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)