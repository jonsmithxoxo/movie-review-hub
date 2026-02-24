from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
import requests, joblib, os, subprocess

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///moviehub.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "super_secret_key"

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


# ---------------- HELPERS ----------------

def fetch_movie(mid, full=False):
    url = f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={mid}"
    if full:
        url += "&plot=full"
    r = requests.get(url).json()
    if r.get("Poster") in ["N/A", None]:
        r["Poster"] = POSTER_FALLBACK
    return r


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


# ---------------- ROUTES ----------------

@app.route("/")
def root():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("signup"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email").lower()
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            return "Email already exists"

        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )

        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for("signin"))

    return render_template("signup.html")


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email").lower()
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))

        return "Invalid credentials"

    return render_template("signin.html")


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
    ids = [
        "tt0111161","tt0068646","tt0468569","tt1375666",
        "tt0133093","tt0109830","tt0120737","tt0167260"
    ]
    movies = [fetch_movie(i) for i in ids]
    return render_template("movies.html", home=movies, movie=None, aggregate=None)


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


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("signin"))


if __name__ == "__main__":
    app.run(debug=True)
