import os
import re
import datetime

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
uri = os.getenv("DATABASE_URL")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://")
db = SQL(uri)

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Variables to hold a users stocks and grand total
    userStocks = []
    grandTotal = 0.0

    # Get the stocks that a user owns
    stocks = db.execute("SELECT name, symbol, shares FROM stocks WHERE user_id = ? AND shares > 0", session["user_id"])

    # Loop through a users stocks to get the current value and total value of each share
    for s in stocks:
        quote = lookup(s["symbol"])
        totalVal = quote["price"] * float(s["shares"])
        stock = {
            "name": s["name"],
            "symbol": s["symbol"],
            "shares": s["shares"],
            "price": quote["price"],
            "total value": totalVal
        }
        userStocks.append(stock)

    # Get users cash balance and username
    user = db.execute("SELECT username, cash FROM users WHERE id = ?", session["user_id"])

    # Loop through stock total values and update grand total, then add grand total to available cash
    for stock in userStocks:
        grandTotal += stock["total value"]
    grandTotal += user[0]["cash"]

    # Render homepage with user's information
    return render_template("index.html", userStocks=userStocks, user=user[0], grandTotal=grandTotal)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure symbol was submitted and exists
        quote = lookup(request.form.get("symbol").strip())
        if not request.form.get("symbol") or not quote:
            return apology("must enter a valid stock symbol", 400)

        # Ensure a number is entered and that it is a positive number
        shares = request.form.get("shares").lstrip("0")
        if not shares or not shares.isdigit() or int(shares) < 0:
            return apology("must enter a valid number of shares", 400)

        # Check that a user can afford to buy the stock/number of shares
        stockVal = float(int(shares)) * quote["price"]
        cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        if stockVal > cash[0]["cash"]:
            return apology("you do not have enough cash to buy those shares", 403)

        # Purchase the stock, update cash and add it to users' stock and history tables
        # Subtract cost of stock from users.cash
        updateCash = cash[0]["cash"] - stockVal
        db.execute("UPDATE users SET cash = ? WHERE id = ?", updateCash, session["user_id"])

        # If a user already owns the stock, update the number of shares they own
        stocks = db.execute("SELECT symbol, shares FROM stocks WHERE user_id = ?", session["user_id"])
        if any(d["symbol"] == quote["symbol"] for d in stocks):
            ownedShares = 0
            for stock in stocks:
                if stock["symbol"] == quote["symbol"]:
                    ownedShares = stock["shares"]
            updateShares = ownedShares + int(shares)
            db.execute("UPDATE stocks SET shares = ? WHERE user_id = ? AND symbol = ?",
                       updateShares, session["user_id"], quote["symbol"])
        else:
            # Else insert the new stock into the stocks table
            db.execute("INSERT INTO stocks (user_id, name, symbol, shares) VALUES(?, ?, ?, ?)",
                       session["user_id"], quote["name"], quote["symbol"], int(shares))

        # Update history table with transaction
        db.execute("INSERT INTO history (user_id, transaction_type, name, symbol, shares, price, time) VALUES(?, ?, ?, ?, ?, ?, ?)",
                   session["user_id"], "BUY", quote["name"], quote["symbol"], int(shares), quote["price"], datetime.datetime.now())

        # Redirect user to homepage
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        # Pass in funds so the user knows how much available cash they have before purchase
        funds = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        return render_template("buy.html", funds=funds[0])


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # Variables to hold a users history
    history = []

    # Get transaction history for a user
    transactions = db.execute("SELECT * FROM history WHERE user_id = ?", session["user_id"])

    # Loop through transactions to get stock info and format time
    for t in transactions:
        time = datetime.datetime.strptime(t["time"], '%Y-%m-%d %H:%M:%S').strftime("%m/%d/%Y - %H:%M:%S")
        transaction = {
            "name": t["name"],
            "symbol": t["symbol"],
            "type": t["transaction_type"],
            "shares": t["shares"],
            "price": t["price"],
            "time": time
        }
        history.append(transaction)

    # Get username
    user = db.execute("SELECT username FROM users WHERE id = ?", session["user_id"])

    # Render history page with user's info
    return render_template("history.html", history=history, user=user[0])


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure symbol was submitted
        quote = lookup(request.form.get("symbol").strip())
        if not request.form.get("symbol") or not quote:
            return apology("must enter a valid stock symbol", 400)

        # render the template and pass the dictionary with the stock quote
        return render_template("quoted.html", quote=quote)

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Ensure confirm password was submitted and passwords match
        elif not request.form.get("confirmation"):
            return apology("must confirm password", 400)
        elif not request.form.get("password") == request.form.get("confirmation"):
            return apology("Passwords do not match", 400)

        # Ensure proper password 8-20 chars, 1 lower, 1 upper, 1 digit, 1 special char
        # Personal touch feature
        reg = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*#?&])[A-Za-z\d@$!#%*?&]{8,20}$"
        pattern = re.compile(reg)
        match = re.search(pattern, request.form.get("password"))
        if not match:
            return apology("Password must be between 8-20 characters and contain at least 1 lowercase letter, 1 uppercase letter, 1 digit, and 1 special character", 400)

        # Query database to make sure that the username doesn't already exist
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username").strip())
        if len(rows) > 0:
            return apology("Username already in use", 400)

        # Store username and hashed password for table insert
        username = request.form.get("username").strip()
        hash = generate_password_hash(request.form.get("password").strip())

        # Add username and hashed password into the db and return the id for session
        id = db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, hash)

        # Remember which user has registered/logged in
        session["user_id"] = id

        # Take user to index.html/home
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure symbol was submitted and exists
        if not request.form.get("symbol"):
            return apology("must choose a valid stock", 400)
        quote = lookup(request.form.get("symbol").strip())
        if not quote:
            return apology("must choose a valid stock", 400)

        # Ensure that user actually owns that stock
        userStocks = db.execute("SELECT symbol, shares FROM stocks WHERE user_id = ?", session["user_id"])
        if not any(d["symbol"] == request.form.get("symbol") for d in userStocks):
            return apology("must choose a valid stock", 400)

        # Ensure a number is entered and that it is a positive number
        shares = request.form.get("shares").lstrip("0")
        if not shares or not shares.isdigit() or int(shares) < 0:
            return apology("must enter a valid number of shares", 400)

        # Ensure that user can't sell more stocks than they own
        sharesOwned = db.execute("SELECT shares FROM stocks WHERE user_id = ? AND symbol =?",
                                 session["user_id"], request.form.get("symbol"))
        if int(shares) > sharesOwned[0]["shares"]:
            return apology("must enter a valid number of shares", 400)

        # Update users' cash
        stockVal = float(int(shares)) * quote["price"]
        cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        updateCash = cash[0]["cash"] + stockVal
        db.execute("UPDATE users SET cash = ? WHERE id = ?", updateCash, session["user_id"])

        # Update users' shares for stock being sold
        ownedShares = 0
        for stock in userStocks:
            if stock["symbol"] == quote["symbol"]:
                ownedShares = stock["shares"]
        updateShares = ownedShares - int(shares)
        db.execute("UPDATE stocks SET shares = ? WHERE user_id = ? AND symbol = ?",
                   updateShares, session["user_id"], quote["symbol"])

        # Update history table with transaction
        db.execute("INSERT INTO history (user_id, transaction_type, name, symbol, shares, price, time) VALUES(?, ?, ?, ?, ?, ?, ?)",
                   session["user_id"], "SELL", quote["name"], quote["symbol"], int(shares), quote["price"], datetime.datetime.now())

        # Redirect user to homepage
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        # Pass in stocks that the user owns for select options
        stocks = db.execute("SELECT symbol FROM stocks WHERE user_id = ? AND shares > 0", session["user_id"])
        return render_template("sell.html", stocks=stocks)


# Wildcard Route
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return apology("page not found", 404)