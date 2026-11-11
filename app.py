from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', 'stockflow-development-key'
)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stockflow.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ORGANIZATION MODEL
class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    default_low_stock_threshold = db.Column(db.Integer, default=5)


# USER MODEL
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey('organization.id'),
        nullable=False,
        unique=True
    )


# PRODUCT MODEL
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey('organization.id'),
        nullable=False
    )
    name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    cost_price = db.Column(db.Float)
    selling_price = db.Column(db.Float)
    low_stock_threshold = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint(
            'organization_id',
            'sku',
            name='unique_sku_per_organization'
        ),
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# CREATE DATABASE
with app.app_context():
    db.create_all()


# HOME
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


# SIGNUP
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        organization_name = request.form.get('organization', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not organization_name or not email or len(password) < 8:
            flash('Please provide valid details. Password must be at least 8 characters.')
            return redirect(url_for('signup'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please log in.')
            return redirect(url_for('login'))

        try:
            organization = Organization(name=organization_name)
            db.session.add(organization)
            db.session.flush()

            user = User(
                email=email,
                password=generate_password_hash(password),
                organization_id=organization.id
            )

            db.session.add(user)
            db.session.commit()

            login_user(user)
            flash('Account created successfully!')
            return redirect(url_for('dashboard'))

        except Exception:
            db.session.rollback()
            flash('Unable to create account. Please try again.')

    return render_template('signup.html')


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))

        flash('Invalid email or password.')

    return render_template('login.html')


# DASHBOARD
@app.route('/dashboard')
@login_required
def dashboard():
    products = Product.query.filter_by(
        organization_id=current_user.organization_id
    ).all()

    total_products = len(products)
    total_quantity = sum(p.quantity for p in products)

    organization = db.session.get(
        Organization, current_user.organization_id
    )
    default_threshold = organization.default_low_stock_threshold

    low_stock_products = [
        p for p in products
        if p.quantity <= (
            p.low_stock_threshold
            if p.low_stock_threshold is not None
            else default_threshold
        )
    ]

    return render_template(
        'dashboard.html',
        total_products=total_products,
        total_quantity=total_quantity,
        low_stock_products=low_stock_products,
        default_threshold=default_threshold
    )

# PRODUCT LIST
@app.route('/products')
@login_required
def products():
    all_products = Product.query.filter_by(
        organization_id=current_user.organization_id
    ).order_by(Product.created_at.desc()).all()

    return render_template(
        'products.html',
        products=all_products
    )


# ADD PRODUCT
@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        sku = request.form.get('sku', '').strip()
        description = request.form.get('description', '').strip()

        try:
            quantity = int(request.form.get('quantity', 0))
            cost_price = float(request.form.get('cost_price') or 0)
            selling_price = float(request.form.get('selling_price') or 0)
            threshold_value = request.form.get('low_stock_threshold', '').strip()
            threshold = int(threshold_value) if threshold_value else None

            if not name or not sku:
                raise ValueError()

            if quantity < 0 or cost_price < 0 or selling_price < 0:
                raise ValueError()

            if threshold is not None and threshold < 0:
                raise ValueError()

        except ValueError:
            flash('Please enter valid product details. Values cannot be negative.')
            return redirect(url_for('add_product'))

        existing = Product.query.filter_by(
            organization_id=current_user.organization_id,
            sku=sku
        ).first()

        if existing:
            flash('This SKU already exists in your organization.')
            return redirect(url_for('add_product'))

        product = Product(
            organization_id=current_user.organization_id,
            name=name,
            sku=sku,
            description=description,
            quantity=quantity,
            cost_price=cost_price,
            selling_price=selling_price,
            low_stock_threshold=threshold
        )

        db.session.add(product)
        db.session.commit()

        flash('Product added successfully!')
        return redirect(url_for('products'))

    return render_template('product_form.html', product=None)


# EDIT PRODUCT
@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.filter_by(
        id=product_id,
        organization_id=current_user.organization_id
    ).first_or_404()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        sku = request.form.get('sku', '').strip()

        try:
            quantity = int(request.form.get('quantity', 0))
            cost_price = float(request.form.get('cost_price') or 0)
            selling_price = float(request.form.get('selling_price') or 0)
            threshold_value = request.form.get('low_stock_threshold', '').strip()
            threshold = int(threshold_value) if threshold_value else None

            if not name or not sku:
                raise ValueError()

            if quantity < 0 or cost_price < 0 or selling_price < 0:
                raise ValueError()

            if threshold is not None and threshold < 0:
                raise ValueError()

        except ValueError:
            flash('Please enter valid product details.')
            return redirect(url_for('edit_product', product_id=product.id))

        duplicate = Product.query.filter(
            Product.organization_id == current_user.organization_id,
            Product.sku == sku,
            Product.id != product.id
        ).first()

        if duplicate:
            flash('This SKU is already used by another product.')
            return redirect(url_for('edit_product', product_id=product.id))

        product.name = name
        product.sku = sku
        product.description = request.form.get('description', '').strip()
        product.quantity = quantity
        product.cost_price = cost_price
        product.selling_price = selling_price
        product.low_stock_threshold = threshold
        product.updated_at = datetime.utcnow()

        db.session.commit()

        flash('Product updated successfully!')
        return redirect(url_for('products'))

    return render_template('product_form.html', product=product)


# DELETE PRODUCT
@app.route('/products/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.filter_by(
        id=product_id,
        organization_id=current_user.organization_id
    ).first_or_404()

    db.session.delete(product)
    db.session.commit()

    flash('Product deleted successfully!')
    return redirect(url_for('products'))
# LOGOUT
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)