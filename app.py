from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
import requests, joblib, os, subprocess

# ---------------- NEW IMPORTS (ADDED) ----------------
import smtplib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# -----------------------------------------------------

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///moviehub.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "super_secret_key"

RECAPTCHA_SECRET_KEY = "6LfRGncsAAAAAHMAOScwdkW6fO601_M-eShq6-qn"

db = SQLAlchemy(app)

login_manager = LoginManager(app)

login_manager.login_view = "signin"


# ---------------- MODELS ----------------

class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(100), unique=True, nullable=False)

    email = db.Column(db.String(150), unique=True, nullable=False)

    password_hash = db.Column(db.String(200), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reviews = db.relationship("Review", backref="author", lazy=True)

    age = db.Column(db.Integer)

    gender = db.Column(db.String(20))

    country = db.Column(db.String(100))

    email_verified = db.Column(db.Boolean, default=False)

    verification_token = db.Column(db.String(200))

    is_admin = db.Column(db.Boolean, default=False)


class Movie(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    imdb_id = db.Column(db.String(20), unique=True)

    title = db.Column(db.String(200))

    poster = db.Column(db.String(300))

    reviews = db.relationship("Review", backref="movie", lazy=True)


class Review(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    review_text = db.Column(db.Text)

    ai_rating = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    movie_id = db.Column(db.Integer, db.ForeignKey("movie.id"))


@login_manager.user_loader
def load_user(user_id):

    return User.query.get(int(user_id))


with app.app_context():

    db.create_all()


# ---------------- AI MODEL ----------------

if not os.path.exists("rating_model.pkl") or not os.path.exists("vectorizer.pkl"):

    subprocess.run(["python", "train_model.py"])


model = joblib.load("rating_model.pkl")

vectorizer = joblib.load("vectorizer.pkl")

OMDB_API_KEY = "thewdb"

POSTER_FALLBACK = "https://via.placeholder.com/300x450?text=No+Poster"


# ---------------- CAPTCHA HELPER ----------------

def verify_captcha(response_token):

    if not response_token:

        return False

    payload = {

        "secret": RECAPTCHA_SECRET_KEY,

        "response": response_token

    }

    r = requests.post(

        "https://www.google.com/recaptcha/api/siteverify",

        data=payload

    )

    result = r.json()

    return result.get("success", False)


# ---------------- EMAIL HELPER ----------------

def send_verification_email(user_email, token):

    verify_link = url_for("verify_email", token=token, _external=True)

    sender_email = "patelmax47@gmail.com"

    sender_password = "kedy evog iedx sulf"

    subject = "Verify your MovieHub account"

    body = f"""
Welcome to MovieHub!

Please verify your email by clicking the link below:

{verify_link}

If you did not create this account please ignore this email.
"""

    msg = MIMEMultipart()

    msg["From"] = sender_email

    msg["To"] = user_email

    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)

    server.starttls()

    server.login(sender_email, sender_password)

    server.send_message(msg)

    server.quit()


# ---------------- HELPERS ----------------

def fetch_movie(mid, full=False):

    url = f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={mid}"

    if full:

        url += "&plot=full"

    r = requests.get(url).json()

    if r.get("Poster") in ["N/A", None]:

        r["Poster"] = POSTER_FALLBACK

    return r


def search_movies(query):

    url = f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}&s={query}"

    try:

        r = requests.get(url).json()

        if r.get("Search"):

            return r["Search"]

    except:

        pass

    return []


def predict_rating(text):

    X = vectorizer.transform([text])

    score = model.predict(X)[0]

    return max(1, min(10, round(score)))


def aggregate(movie_obj):

    if not movie_obj or not movie_obj.reviews:

        return None

    reviews = movie_obj.reviews

    avg = sum(r.ai_rating for r in reviews) / len(reviews)

    stars = round(avg / 2)

    sentiment = "Positive" if avg >= 7 else "Neutral" if avg >= 4 else "Negative"
 
    return (round(avg, 1), stars, sentiment, len(reviews))


# ================= ADMIN EXTRA ROUTES (ADDED ONLY) =================

@app.route("/delete_user/<int:user_id>")
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return "Unauthorized"
    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/make_admin/<int:user_id>")
@login_required
def make_admin(user_id):
    if not current_user.is_admin:
        return "Unauthorized"
    user = User.query.get(user_id)
    if user:
        user.is_admin = True
        db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/remove_admin/<int:user_id>")
@login_required
def remove_admin(user_id):
    if not current_user.is_admin:
        return "Unauthorized"
    user = User.query.get(user_id)
    if user:
        user.is_admin = False
        db.session.commit()
    return redirect(url_for("admin_dashboard"))


# ---------------- ROUTES ----------------

@app.route("/admin")
@login_required
def admin_dashboard():

    if not current_user.is_admin:
        return "Access Denied"

    users = User.query.all()
    reviews = Review.query.all()
    movies = Movie.query.all()

    total_users = len(users)
    total_reviews = len(reviews)
    total_movies = len(movies)

    movie_count = {}
    for r in reviews:
        movie = Movie.query.get(r.movie_id)
        if movie:
            movie_count[movie.title] = movie_count.get(movie.title, 0) + 1

    top_movies = sorted(movie_count.items(), key=lambda x: x[1], reverse=True)[:5]

    country_count = {}
    for u in users:
        if u.country:
            country_count[u.country] = country_count.get(u.country, 0) + 1

    age_groups = {"<18":0, "18-25":0, "26-35":0, "36-50":0, "50+":0}

    for u in users:
        if u.age:
            age = int(u.age)
            if age < 18:
                age_groups["<18"] += 1
            elif age <= 25:
                age_groups["18-25"] += 1
            elif age <= 35:
                age_groups["26-35"] += 1
            elif age <= 50:
                age_groups["36-50"] += 1
            else:
                age_groups["50+"] += 1

    gender_count = {}
    for u in users:
        if u.gender:
            gender_count[u.gender] = gender_count.get(u.gender, 0) + 1

    country_movie = {}
    for r in reviews:
        user = User.query.get(r.user_id)
        movie = Movie.query.get(r.movie_id)
        if user and movie:
            key = f"{user.country} - {movie.title}"
            country_movie[key] = country_movie.get(key, 0) + 1

    user_activity = {}
    for r in reviews:
        user = User.query.get(r.user_id)
        if user:
            user_activity[user.username] = user_activity.get(user.username, 0) + 1

    top_users = sorted(user_activity.items(), key=lambda x: x[1], reverse=True)[:5]

    recent_reviews = reviews[-5:]
    recent_data = []

    for r in recent_reviews:
        user = User.query.get(r.user_id)
        movie = Movie.query.get(r.movie_id)

        recent_data.append({
            "user": user.username if user else "Unknown",
            "movie": movie.title if movie else "Unknown",
            "rating": r.ai_rating
        })

    insight = "Users are highly engaged with action & thriller content 🔥"

    return render_template(
        "admin.html",
        total_users=total_users,
        total_reviews=total_reviews,
        total_movies=total_movies,
        top_movies=top_movies,
        country_count=country_count,
        age_groups=age_groups,
        gender_count=gender_count,
        country_movie=country_movie,
        top_users=top_users,
        recent_data=recent_data,
        insight=insight,
        users=users
    )

# (REST OF YOUR FILE REMAINS EXACT SAME — NO CHANGE BELOW)

@app.route("/")
def index():

    ids = [

        "tt0111161",

        "tt0068646",

        "tt0468569",

        "tt1375666",

        "tt0133093",

        "tt0109830"

    ]

    movies = [fetch_movie(i) for i in ids]

    return render_template("index.html", movies=movies)


@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        captcha_response = request.form.get("g-recaptcha-response")

        if not verify_captcha(captcha_response):

            return "Captcha verification failed."

        username = request.form.get("username")

        email = request.form.get("email").lower()

        password = request.form.get("password")

        age = request.form.get("age")

        gender = request.form.get("gender")

        country = request.form.get("country")

        token = secrets.token_urlsafe(32)

        new_user = User(

            username=username,

            email=email,

            password_hash=generate_password_hash(password),

            age=age,

            gender=gender,

            country=country,

            email_verified=False,

            verification_token=token

        )

        db.session.add(new_user)

        db.session.commit()

        send_verification_email(email, token)

        return redirect(url_for("signin"))

    return render_template("signup.html")


@app.route("/signin", methods=["GET", "POST"])
def signin():

    if request.method == "POST":

        captcha_response = request.form.get("g-recaptcha-response")

        if not verify_captcha(captcha_response):

            return "Captcha verification failed."

        email = request.form.get("email").lower()
 
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):

            if not user.email_verified:

                return "Please verify your email before signing in."

            login_user(user)

            return redirect(url_for("dashboard"))

    return render_template("signin.html")


# ---------------- UPDATED HOME ROUTE ----------------

# ---------------- DASHBOARD ROUTE ----------------

@app.route("/dashboard")
@login_required
def dashboard():

    user_reviews = (
        Review.query
        .filter_by(user_id=current_user.id)
        .order_by(Review.created_at.desc())
        .all()
    )
   
    review_data = []

    for r in user_reviews:

        movie = Movie.query.get(r.movie_id)

        sentiment = "Positive" if r.ai_rating >= 7 else \
                    "Neutral" if r.ai_rating >= 4 else \
                    "Negative"

        review_data.append({

            "movie_title": movie.title if movie else "Unknown",

            "review_text": r.review_text,

            "rating": r.ai_rating,

            "sentiment": sentiment,

            "created_at": r.created_at.strftime("%d %b %Y • %I:%M %p")

        })

    return render_template(
        "dashboard.html",
        reviews=review_data
    )

@app.route("/home")
@login_required
def home():

    query = request.args.get("q")

    ids = [

        "tt0111161","tt0068646","tt0468569","tt1375666",

        "tt0133093","tt0109830","tt0120737","tt0167260"

    ]

    if query:

        movies = search_movies(query)

        return render_template(

            "movies.html",

            home=movies,

            movie=None,

            aggregate=None,

            query=query,

            searching=True

        )

    movies = [fetch_movie(i) for i in ids]

    return render_template(

        "movies.html",

        home=movies,

        movie=None,

        aggregate=None,

        query="",

        searching=False

    )


@app.route("/movie/<imdb_id>", methods=["GET", "POST"])
@login_required
def movie_detail(imdb_id):

    if request.method == "POST":

        text = request.form.get("review")

        rating = predict_rating(text)

        movie = Movie.query.filter_by(imdb_id=imdb_id).first()

        if not movie:

            data = fetch_movie(imdb_id)

            movie = Movie(

                imdb_id=imdb_id,

                title=data["Title"],

                poster=data["Poster"]

            )

            db.session.add(movie)

            db.session.commit()

        review = Review(

            review_text=text,

            ai_rating=rating,

            user_id=current_user.id,

            movie_id=movie.id

        )

        db.session.add(review)

        db.session.commit()

        return redirect(url_for("movie_detail", imdb_id=imdb_id))

    movie_data = fetch_movie(imdb_id, full=True)

    movie_obj = Movie.query.filter_by(imdb_id=imdb_id).first()

    agg = aggregate(movie_obj)

    return render_template("movies.html", movie=movie_data, aggregate=agg, home=None)

 # ===========================
# EMAIL VERIFICATION ROUTE (APPENDED - DO NOT REMOVE ANYTHING ABOVE)
# ===========================

@app.route("/verify/<token>")
def verify_email(token):

    user = User.query.filter_by(verification_token=token).first()

    if not user:
        return "Invalid or expired token"

    user.email_verified = True
    user.verification_token = None

    db.session.commit()

    return "Email verified successfully! You can now login."


@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(url_for("signin"))


if __name__ == "__main__":

    app.run(debug=True)

   