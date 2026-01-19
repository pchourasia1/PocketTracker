import math
import os
import re
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import CATEGORIES, get_db, init_db, seed_db

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

init_db()
seed_db()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
MAX_DESCRIPTION_LENGTH = 200

PERIODS = {
    "all": "All time",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "month": "This month",
    "custom": "Custom range",
}


@app.template_filter("money")
def money(value):
    return f"${value:,.2f}"


# ------------------------------------------------------------------ #
# Auth helpers                                                        #
# ------------------------------------------------------------------ #

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def log_in(user_id, name):
    session.clear()
    session["user_id"] = user_id
    session["user_name"] = name


# ------------------------------------------------------------------ #
# Expense helpers                                                     #
# ------------------------------------------------------------------ #

def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def date_range(period, start_arg, end_arg):
    """Return (start, end) dates for a filter period; either may be None (unbounded)."""
    today = date.today()
    if period == "7d":
        return today - timedelta(days=6), today
    if period == "30d":
        return today - timedelta(days=29), today
    if period == "month":
        return today.replace(day=1), today
    if period == "custom":
        return parse_date(start_arg), parse_date(end_arg)
    return None, None


def validate_expense(form):
    """Return (values, error) for a submitted expense form."""
    values = {
        "amount": form.get("amount", "").strip(),
        "category": form.get("category", ""),
        "date": form.get("date", "").strip(),
        "description": form.get("description", "").strip(),
    }
    try:
        amount = round(float(values["amount"]), 2)
    except ValueError:
        return values, "Please enter a valid amount."
    if not math.isfinite(amount) or amount <= 0:
        return values, "Amount must be greater than zero."
    if values["category"] not in CATEGORIES:
        return values, "Please choose a category."
    if parse_date(values["date"]) is None:
        return values, "Please enter a valid date."
    if len(values["description"]) > MAX_DESCRIPTION_LENGTH:
        return values, f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer."
    values["amount"] = amount
    return values, None


def get_own_expense(conn, expense_id):
    expense = conn.execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, session["user_id"]),
    ).fetchone()
    if expense is None:
        conn.close()
        abort(404)
    return expense


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    error = None
    if not name:
        error = "Please enter your name."
    elif not EMAIL_RE.match(email):
        error = "Please enter a valid email address."
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    if error is None:
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            conn.commit()
            user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            error = "An account with that email already exists."
        finally:
            conn.close()

    if error:
        return render_template("register.html", error=error, name=name, email=email), 400

    log_in(user_id, name)
    return redirect(url_for("profile"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("profile"))
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    conn = get_db()
    user = conn.execute(
        "SELECT id, name, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()

    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.", email=email), 401

    log_in(user["id"], user["name"])
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
@login_required
def profile():
    period = request.args.get("period", "all")
    if period not in PERIODS:
        period = "all"
    start, end = date_range(period, request.args.get("start"), request.args.get("end"))

    where = "WHERE user_id = ?"
    params = [session["user_id"]]
    if start:
        where += " AND date >= ?"
        params.append(start.isoformat())
    if end:
        where += " AND date <= ?"
        params.append(end.isoformat())

    conn = get_db()
    user = conn.execute(
        "SELECT name, email, created_at FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()
    expenses = conn.execute(
        f"SELECT * FROM expenses {where} ORDER BY date DESC, id DESC", params
    ).fetchall()
    by_category = conn.execute(
        f"SELECT category, SUM(amount) AS total, COUNT(*) AS count FROM expenses {where} "
        "GROUP BY category ORDER BY total DESC",
        params,
    ).fetchall()
    conn.close()

    total = sum(e["amount"] for e in expenses)
    top_total = by_category[0]["total"] if by_category else 0

    return render_template(
        "profile.html",
        user=user,
        expenses=expenses,
        by_category=by_category,
        total=total,
        top_total=top_total,
        periods=PERIODS,
        period=period,
        start=start.isoformat() if start else "",
        end=end.isoformat() if end else "",
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    if request.method == "GET":
        values = {"date": date.today().isoformat()}
        return render_template("expense_form.html", values=values, categories=CATEGORIES, editing=False)

    values, error = validate_expense(request.form)
    if error:
        return render_template(
            "expense_form.html", values=values, categories=CATEGORIES, editing=False, error=error
        ), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (session["user_id"], values["amount"], values["category"], values["date"], values["description"]),
    )
    conn.commit()
    conn.close()
    flash("Expense added.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(id):
    conn = get_db()
    expense = get_own_expense(conn, id)

    if request.method == "GET":
        conn.close()
        return render_template("expense_form.html", values=expense, categories=CATEGORIES, editing=True, id=id)

    values, error = validate_expense(request.form)
    if error:
        conn.close()
        return render_template(
            "expense_form.html", values=values, categories=CATEGORIES, editing=True, id=id, error=error
        ), 400

    conn.execute(
        "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? WHERE id = ? AND user_id = ?",
        (values["amount"], values["category"], values["date"], values["description"], id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    flash("Expense updated.")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete", methods=["POST"])
@login_required
def delete_expense(id):
    conn = get_db()
    get_own_expense(conn, id)
    conn.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Expense deleted.")
    return redirect(url_for("profile"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
