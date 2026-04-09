import os
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Expense, User
from datetime import datetime
import json

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'expenses.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-for-flash-messages-v2'

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('register'))
        new_user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                flash(f'Welcome back, {user.username}!', 'success')
                return redirect(url_for('index'))
            flash('Invalid username or password.', 'danger')
        return render_template('login.html')
    except Exception as e:
        import traceback
        return str(traceback.format_exc()), 500

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    page = request.args.get('page', 1, type=int)

    query = Expense.query.filter_by(user_id=current_user.id)
    
    if start_date:
        query = query.filter(Expense.date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(Expense.date <= datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))

    query = query.order_by(Expense.date.desc())
    
    pagination = query.paginate(page=page, per_page=10, error_out=False)
    expenses = pagination.items

    all_filtered_expenses = query.all()
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    monthly_total = sum(e.amount for e in all_filtered_expenses if e.date.month == current_month and e.date.year == current_year)
    budget_exceeded = monthly_total > current_user.budget_limit
    
    categories = {}
    for e in all_filtered_expenses:
        categories[e.category] = categories.get(e.category, 0) + e.amount
            
    monthly_trend = {i: 0 for i in range(1, 13)}
    for e in all_filtered_expenses:
        if e.date.year == current_year:
            monthly_trend[e.date.month] += e.amount

    return render_template('index.html', 
                           expenses=expenses, 
                           pagination=pagination,
                           start_date=start_date or '',
                           end_date=end_date or '',
                           monthly_total=monthly_total,
                           budget_limit=current_user.budget_limit,
                           budget_exceeded=budget_exceeded,
                           category_labels=json.dumps(list(categories.keys())),
                           category_data=json.dumps(list(categories.values())),
                           trend_labels=json.dumps(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']),
                           trend_data=json.dumps([monthly_trend[i] for i in range(1, 13)]))

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        amount = request.form.get('amount')
        category = request.form.get('category')
        date_str = request.form.get('date')
        description = request.form.get('description')
        
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
            new_expense = Expense(
                amount=float(amount),
                category=category,
                date=date_obj,
                description=description,
                user_id=current_user.id
            )
            db.session.add(new_expense)
            db.session.commit()
            flash('Expense added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error adding expense: {str(e)}', 'danger')
            db.session.rollback()
            
    return render_template('form.html', form_type='Add')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_expense(id):
    expense = Expense.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        amount = request.form.get('amount')
        category = request.form.get('category')
        date_str = request.form.get('date')
        description = request.form.get('description')
        
        try:
            expense.amount = float(amount)
            expense.category = category
            if date_str:
                expense.date = datetime.strptime(date_str, '%Y-%m-%d')
            expense.description = description
            
            db.session.commit()
            flash('Expense updated successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error updating expense: {str(e)}', 'danger')
            db.session.rollback()
            
    return render_template('form.html', form_type='Edit', expense=expense)

@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_expense(id):
    expense = Expense.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    try:
        db.session.delete(expense)
        db.session.commit()
        flash('Expense deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting expense: {str(e)}', 'danger')
        db.session.rollback()
    return redirect(url_for('index'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        budget = request.form.get('budget_limit')
        try:
            current_user.budget_limit = float(budget)
            db.session.commit()
            flash('Settings updated successfully.', 'success')
        except ValueError:
            flash('Invalid budget amount.', 'danger')
        return redirect(url_for('settings'))
    return render_template('settings.html')

@app.route('/export')
@login_required
def export_csv():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = Expense.query.filter_by(user_id=current_user.id)
    if start_date:
        query = query.filter(Expense.date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(Expense.date <= datetime.strptime(end_date + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))

    expenses = query.order_by(Expense.date.desc()).all()

    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('Date', 'Category', 'Description', 'Amount'))
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)

        for e in expenses:
            writer.writerow((e.date.strftime('%Y-%m-%d'), e.category, e.description, f"{e.amount:.2f}"))
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="expenses.csv")
    return response

if __name__ == '__main__':
    app.run(debug=True)
