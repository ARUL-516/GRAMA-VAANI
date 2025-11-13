# --------------------------------------------------------------------------
# Grama Vaani - AI Farming Assistant (FULL MONOLITHIC CODE - CORRECTED)
# --------------------------------------------------------------------------
# Features: Login, Signup, Protected Dashboard, Voice, Image, Weather, History, SUGGESTED QUESTIONS
# NEW FEATURE: Location-Aware Daily Crop Advisory
# Run: pip install fastapi uvicorn pymongo "passlib[bcrypt]" python-jose "pydantic[email]" google-cloud-texttospeech google-cloud-vision vertexai httpx python-dotenv
# Open: http://127.0.0.1:8000
# --------------------------------------------------------------------------

import os
import re
import base64
import uvicorn
import httpx
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

from fastapi import (
    FastAPI, File, UploadFile, HTTPException, Query, Form, Depends, Request, Response
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional

from bson.objectid import ObjectId

# Google Cloud
from google.cloud import texttospeech, vision
import vertexai
from vertexai.generative_models import GenerativeModel, ChatSession, Part

# Auth
import pymongo 
from passlib.context import CryptContext 
from jose import JWTError, jwt 

# Load environment variables from .env file
load_dotenv()

# --------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "cobalt-duality-469507-b1")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
# Ensure the GOOGLE_APPLICATION_CREDENTIALS environment variable is set for local testing
GOOGLE_APPLICATION_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS_PATH",
    r"C:\Users\Arul\Desktop\gramvaniapp\venv\cobalt-duality-469507-b1-e973463a6ee2.json"
)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS_PATH

# Auth CONFIGURATION
SECRET_KEY = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 1 day

# DB SETUP (MongoDB)
MONGO_CONNECTION_STRING = os.getenv("MONGO_URL", "mongodb://localhost:27017/")
db_client = pymongo.MongoClient(MONGO_CONNECTION_STRING)
db = db_client["grama_vaani_db"]
users_collection = db["users"]
chats_collection = db["chats"] 

try:
    users_collection.create_index("email", unique=True)
except Exception as e:
    print(f"Could not create index (this is normal if already exists): {e}")

# --- API Keys/URLs ---
GOVT_SCHEME_API_KEY = "579b464db66ec23bdd000001c70d5371a46f42956f9f9a9e7034defd"
GOVT_SCHEME_API_URL = "https://api.data.gov.in/resource/6176ee09-3d56-4a3b-8115-2184157c1f41"

# --------------------------------------------------------------------------
# AUTH & PYDANTIC MODELS
# --------------------------------------------------------------------------

# AUTH HELPER FUNCTIONS
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Pydantic Models
class TokenData(BaseModel):
    email: str | None = None

class User(BaseModel):
    email: EmailStr
    name: str
    phone: str
    location: Optional[str] = Field(default="India", max_length=100)
    preferred_crop: Optional[str] = Field(default="Paddy", max_length=50)

class UserInDB(User):
    hashed_password: str

class UserCreate(User):
    password: str = Field(..., min_length=8, max_length=72)
    location: Optional[str] = Field(default="India", max_length=100) 
    preferred_crop: Optional[str] = Field(default="Paddy", max_length=50)

class UserLogin(BaseModel):
    email: str 
    password: str
    
class Token(BaseModel):
    access_token: str
    token_type: str

class UserUpdateProfile(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    preferred_crop: Optional[str] = None

class Message(BaseModel):
    role: str
    text: str

class ChatSaveRequest(BaseModel):
    chat_id: Optional[str] = None
    messages: List[Message]

class ChatSessionInfo(BaseModel):
    id: str
    title: str

class ChatSessionDetail(BaseModel):
    id: str
    title: str
    messages: List[Message]

class SuggestedQuestionsRequest(BaseModel):
    history: List[Message]
    language: str

class AdvisoryResponse(BaseModel):
    text: str
    audio: Optional[str] = None

class ChatRequest(BaseModel):
    text: str
    language: str

# --------------------------------------------------------------------------
# HTML CONTENT (LOGIN PAGE)
# --------------------------------------------------------------------------

LOGIN_HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grama Vaani - Login</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        :root {
            --primary-green: #10b981;
            --primary-green-dark: #059669;
            --bg-dark: #0a0a0a;
            --bg-card: rgba(23, 23, 23, 0.95);
            --text-primary: #f5f5f5;
            --text-secondary: #a3a3a3;
            --border-color: rgba(255, 255, 255, 0.1);
            --shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            --error: #ef4444;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', sans-serif;
            background: var(--bg-dark);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }
        .background {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
        }
        .background::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(5, 150, 105, 0.05) 100%);
            z-index: 2;
        }
        .background::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            filter: blur(2px) brightness(0.45);
            z-index: 1;
        }
        .gradient-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(45deg,
                rgba(16, 185, 129, 0.2) 0%,
                rgba(5, 150, 105, 0.1) 25%,
                rgba(16, 185, 129, 0.15) 50%,
                rgba(5, 150, 105, 0.1) 75%,
                rgba(16, 185, 129, 0.2) 100%);
            background-size: 400% 400%;
            animation: gradientShift 15s ease infinite;
            z-index: 2;
        }
        @keyframes gradientShift {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
        }
        .login-container {
            position: relative;
            z-index: 10;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }
        .login-card {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            box-shadow: var(--shadow);
            width: 100%;
            max-width: 440px;
            padding: 3rem;
            animation: slideUp 0.6s ease-out;
        }
        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .logo-section {
            text-align: center;
            margin-bottom: 2.5rem;
        }
        .logo {
            width: 72px;
            height: 72px;
            background: linear-gradient(135deg, var(--primary-green) 0%, var(--primary-green-dark) 100%);
            border-radius: 18px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 2.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 8px 24px rgba(16, 185, 129, 0.3);
            animation: logoFloat 3s ease-in-out infinite;
        }
        @keyframes logoFloat {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }
        .logo-title {
            font-size: 1.875rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--text-secondary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .logo-subtitle {
            font-size: 0.9375rem;
            color: var(--text-secondary);
            font-weight: 400;
        }
        .auth-tabs {
            display: flex;
            gap: 0.5rem;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 0.375rem;
            margin-bottom: 2rem;
        }
        .tab-btn {
            flex: 1;
            padding: 0.75rem;
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-size: 0.9375rem;
            font-weight: 500;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .tab-btn.active {
            background: var(--primary-green);
            color: white;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }
        .tab-btn:hover:not(.active) {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.05);
        }
        .auth-form {
            display: none;
        }
        .auth-form.active {
            display: block;
            animation: fadeIn 0.4s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        .form-label {
            display: block;
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
        }
        .input-wrapper {
            position: relative;
        }
        .input-icon {
            position: absolute;
            left: 1rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-secondary);
            font-size: 1.125rem;
            z-index: 1;
        }
        .form-input {
            width: 100%;
            padding: 0.875rem 1rem 0.875rem 3rem;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            color: var(--text-primary);
            font-size: 0.9375rem;
            transition: all 0.3s ease;
        }
        .form-input:focus {
            outline: none;
            background: rgba(255, 255, 255, 0.08);
            border-color: var(--primary-green);
            box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.1);
        }
        .form-input::placeholder {
            color: var(--text-secondary);
        }
        .toggle-password {
            position: absolute;
            right: 1rem;
            top: 50%;
            transform: translateY(-50%);
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 1.125rem;
            padding: 0.25rem;
            transition: color 0.2s;
        }
        .toggle-password:hover {
            color: var(--text-primary);
        }
        .form-options {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }
        .remember-me {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            cursor: pointer;
        }
        .remember-me input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: var(--primary-green);
        }
        .remember-me label {
            font-size: 0.875rem;
            color: var(--text-secondary);
            cursor: pointer;
        }
        .forgot-link {
            font-size: 0.875rem;
            color: var(--primary-green);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.2s;
        }
        .forgot-link:hover {
            color: var(--primary-green-dark);
        }
        .submit-btn {
            width: 100%;
            padding: 0.875rem;
            background: var(--primary-green);
            border: none;
            border-radius: 12px;
            color: white;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }
        .submit-btn:hover {
            background: var(--primary-green-dark);
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(16, 185, 129, 0.4);
        }
        .submit-btn:active {
            transform: translateY(0);
        }
        .divider {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin: 2rem 0;
        }
        .divider-line {
            flex: 1;
            height: 1px;
            background: var(--border-color);
        }
        .divider-text {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }
        .social-login {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.75rem;
        }
        .social-btn {
            padding: 0.875rem;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            color: var(--text-primary);
            font-size: 0.9375rem;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            transition: all 0.3s ease;
            text-decoration: none; /* For the 'a' tag */
        }
        .social-btn:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: var(--primary-green);
            transform: translateY(-2px);
        }
        .social-btn i {
            font-size: 1.25rem;
        }
        .terms {
            margin-top: 2rem;
            text-align: center;
            font-size: 0.8125rem;
            color: var(--text-secondary);
            line-height: 1.6;
        }
        .terms a {
            color: var(--primary-green);
            text-decoration: none;
            font-weight: 500;
        }
        .terms a:hover {
            text-decoration: underline;
        }
        .loading {
            pointer-events: none;
            opacity: 0.7;
        }
        .loading .submit-btn-text {
            display: none;
        }
        .loading .submit-btn-spinner {
            display: inline-block;
        }
        .submit-btn-spinner {
            display: none;
            width: 16px;
            height: 16px;
            border: 2px solid white;
            border-radius: 50%;
            border-top-color: transparent;
            animation: spin 0.6s linear infinite;
            vertical-align: middle;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .error-message {
            background: rgba(239, 68, 68, 0.1);
            color: var(--error);
            border: 1px solid var(--error);
            padding: 1rem;
            border-radius: 12px;
            font-size: 0.875rem;
            text-align: center;
            margin-bottom: 1.5rem;
            display: none; /* Hidden by default */
        }
    </style>
</head>
<body>
    <div class="background"></div>
    <div class="gradient-overlay"></div>
    <div class="login-container">
        <div class="login-card">
            <div class="logo-section">
                <div class="logo">🌾</div>
                <h1 class="logo-title">Grama Vaani</h1>
                <p class="logo-subtitle">AI-Powered Farming Assistant</p>
            </div>
            <div class="auth-tabs">
                <button class="tab-btn active" data-tab="login">Sign In</button>
                <button class="tab-btn" data-tab="signup">Sign Up</button>
            </div>
            
            <div class="error-message" id="errorMessage"></div>

            <form class="auth-form active" id="loginForm">
                <div class="form-group">
                    <label class="form-label">Email</label>
                    <div class="input-wrapper">
                        <i class="bi bi-person input-icon"></i>
                        <input type="email" class="form-input" id="loginEmail" placeholder="Enter your email" required>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <div class="input-wrapper">
                        <i class="bi bi-lock input-icon"></i>
                        <input type="password" class="form-input" id="loginPassword" placeholder="Enter your password" required>
                        <button type="button" class="toggle-password" data-target="loginPassword">
                            <i class="bi bi-eye"></i>
                        </button>
                    </div>
                </div>
                <div class="form-options">
                    <div class="remember-me">
                        <input type="checkbox" id="rememberMe">
                        <label for="rememberMe">Remember me</label>
                    </div>
                    <a href="#" class="forgot-link">Forgot password?</a>
                </div>
                <button type="submit" class="submit-btn">
                    <span class="submit-btn-text">Sign In</span>
                    <span class="submit-btn-spinner"></span>
                </button>
                <div class="divider">
                    <div class="divider-line"></div>
                    <span class="divider-text">Or continue with</span>
                    <div class="divider-line"></div>
                </div>
                <div class="social-login">
                    <a href="/auth/google" class="social-btn">
                        <i class="bi bi-google"></i>
                        <span>Google</span>
                    </a>
                    <button type="button" class="social-btn" id="phoneLoginBtn">
                        <i class="bi bi-phone"></i>
                        <span>Phone</span>
                    </button>
                </div>
            </form>

            <form class="auth-form" id="signupForm">
                <div class="form-group">
                    <label class="form-label">Full Name</label>
                    <div class="input-wrapper">
                        <i class="bi bi-person input-icon"></i>
                        <input type="text" class="form-input" id="signupName" placeholder="Enter your full name" required>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Email</label>
                    <div class="input-wrapper">
                        <i class="bi bi-envelope input-icon"></i>
                        <input type="email" class="form-input" id="signupEmail" placeholder="Enter your email" required>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Phone Number</label>
                    <div class="input-wrapper">
                        <i class="bi bi-phone input-icon"></i>
                        <input type="tel" class="form-input" id="signupPhone" placeholder="Enter your phone number" required>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <div class="input-wrapper">
                        <i class="bi bi-lock input-icon"></i>
                        <input type="password" class="form-input" id="signupPassword" placeholder="Create a password" required>
                        <button type="button" class="toggle-password" data-target="signupPassword">
                            <i class="bi bi-eye"></i>
                        </button>
                    </div>
                </div>
                <button type="submit" class="submit-btn">
                    <span class="submit-btn-text">Create Account</span>
                    <span class="submit-btn-spinner"></span>
                </button>
            </form>
            
            <div class="terms">
                By continuing, you agree to our <a href="#">Terms of Service</a> and <a href="#">Privacy Policy</a>
            </div>
        </div>
    </div>
    
    <script>
        const errorMessage = document.getElementById('errorMessage');

        function showLoading(form, isLoading) {
            if (isLoading) {
                form.classList.add('loading');
            } else {
                form.classList.remove('loading');
            }
        }

        function showError(message) {
            errorMessage.textContent = message;
            errorMessage.style.display = 'block';
        }

        function hideError() {
            errorMessage.style.display = 'none';
        }

        // Tab Switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                
                // Update active tab
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                // Show corresponding form
                document.querySelectorAll('.auth-form').forEach(form => form.classList.remove('active'));
                document.getElementById(tab + 'Form').classList.add('active');
                hideError();
            });
        });

        // Password Toggle
        document.querySelectorAll('.toggle-password').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.dataset.target;
                const input = document.getElementById(targetId);
                const icon = btn.querySelector('i');
                
                if (input.type === 'password') {
                    input.type = 'text';
                    icon.className = 'bi bi-eye-slash';
                } else {
                    input.type = 'password';
                    icon.className = 'bi bi-eye';
                    input.focus();
                }
            });
        });

        // Login Form Submit
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            hideError();
            showLoading(e.target, true);

            const email = document.getElementById('loginEmail').value;
            const password = document.getElementById('loginPassword').value;
            
            try {
                const response = await fetch('/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email, password: password })
                });

                if (response.ok) {
                    window.location.href = '/dashboard';
                } else {
                    const data = await response.json();
                    showError(data.detail || 'Login failed. Please check your credentials.');
                }
            } catch (err) {
                console.error('Login error:', err);
                showError('An error occurred. Please try again.');
            } finally {
                showLoading(e.target, false);
            }
        });

        // Signup Form Submit
        document.getElementById('signupForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            hideError();
            showLoading(e.target, true);

            const name = document.getElementById('signupName').value;
            const email = document.getElementById('signupEmail').value;
            const phone = document.getElementById('signupPhone').value;
            const password = document.getElementById('signupPassword').value;
            
            try {
                const response = await fetch('/signup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email, phone, password })
                });

                if (response.ok) {
                    window.location.href = '/dashboard';
                } else {
                    const data = await response.json();
                    
                    if (data.detail && Array.isArray(data.detail)) {
                        const pwError = data.detail.find(err => err.loc && err.loc.includes('password'));
                        const emailError = data.detail.find(err => err.loc && err.loc.includes('email'));

                        if (pwError) {
                           showError(pwError.msg.includes('String should have at most 72 characters') ? 'Password must be 72 characters or less.' : pwError.msg);
                        } else if (emailError) {
                             showError(emailError.msg); 
                        } else {
                             showError(data.detail[0].msg);
                        }
                    } else {
                        showError(data.detail || 'Sign up failed. Please try again.');
                    }
                }
            } catch (err) {
                console.error('Signup error:', err);
                showError('An error occurred. Please try again.');
            } finally {
                showLoading(e.target, false);
            }
        });

        // Social Login
        document.getElementById('phoneLoginBtn').addEventListener('click', () => {
            alert('Phone login is complex and requires a service like Firebase or Twilio. This needs to be set up on the backend.');
        });
    </script>
</body>
</html>
"""

# --------------------------------------------------------------------------
# HTML CONTENT (DASHBOARD PAGE)
# --------------------------------------------------------------------------

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Grama Vaani - AI Farming Assistant</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
    
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #171717;
            --bg-tertiary: #1f1f1f;
            --bg-hover: #2a2a0a;
            --accent-primary: #10b981;
            --accent-hover: #059669;
            --text-primary: #f5f5f5;
            --text-secondary: #a3a3a3;
            --text-tertiary: #737373;
            --border-color: #2a2a2a;
            --user-bg: #10b981;
            --ai-bg: #262626;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.4);
            --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.5);
            --question-bar-width: 270px; 
            --advisory-bg: #1e3a8a; 
            --advisory-text: #e0f2f1; 
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            overflow: hidden;
            height: 100vh;
        }

        .app-container {
            display: flex;
            height: 100vh;
            position: relative;
        }

        /* Sidebar */
        .sidebar {
            width: 260px;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 100;
        }

        .sidebar-header {
            padding: 1.25rem 1rem;
            border-bottom: 1px solid var(--border-color);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.125rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .logo-icon {
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, var(--accent-primary) 0%, #059669 100%);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
        }

        .new-chat-btn {
            margin: 1rem;
            padding: 0.75rem 1rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            transition: all 0.2s;
        }

        .new-chat-btn:hover {
            background: var(--bg-hover);
            border-color: var(--accent-primary);
        }

        .nav-section {
            overflow-y: auto;
            padding: 0.5rem;
        }

        .nav-section::-webkit-scrollbar {
            width: 4px;
        }

        .nav-section::-webkit-scrollbar-track {
            background: transparent;
        }

        .nav-section::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 2px;
        }

        .nav-item {
            padding: 0.75rem 1rem;
            margin: 0.25rem 0;
            border-radius: 8px;
            color: var(--text-secondary);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 0.875rem;
            transition: all 0.2s;
        }
        
        .chat-history-item {
            padding: 0.75rem 1rem;
            margin: 0.25rem 0;
            border-radius: 8px;
            color: var(--text-secondary);
            cursor: pointer;
            display: block; 
            width: 100%; 
            text-align: left; 
            font-size: 0.875rem;
            transition: all 0.2s;
            background: transparent; 
            border: none; 
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .nav-item:hover, .chat-history-item:hover {
            background: var(--bg-tertiary);
            color: var(--text-primary);
        }

        .nav-item.active {
            background: var(--bg-tertiary);
            color: var(--accent-primary);
            font-weight: 500;
        }
        
        .chat-history-item.active {
            background: var(--accent-primary);
            color: white; 
            font-weight: 500;
        }

        .nav-item i {
            font-size: 1.125rem;
            width: 20px;
        }
        
        .sidebar-divider {
            padding: 0 1.25rem;
            color: var(--text-tertiary);
            font-size: 0.75rem;
            margin-top: 1rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        
        .logout-btn {
            margin-top: auto; 
            padding: 1rem;
            color: var(--text-tertiary);
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            transition: all 0.2s;
            border-top: 1px solid var(--border-color);
        }
        .logout-btn:hover {
            background: var(--bg-tertiary);
            color: #ef4444; 
        }


        /* Main Content */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden; 
            position: relative;
        }

        /* Header */
        .header {
            height: 60px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 1.5rem;
            flex-shrink: 0;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .menu-toggle {
            display: none;
            background: none;
            border: none;
            color: var(--text-primary);
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0.5rem;
            border-radius: 8px;
            transition: background 0.2s;
        }

        .menu-toggle:hover {
            background: var(--bg-tertiary);
        }

        .view-title {
            font-size: 1rem;
            font-weight: 500;
            color: var(--text-primary);
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .language-selector {
            padding: 0.5rem 0.75rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 0.875rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .language-selector:hover {
            border-color: var(--accent-primary);
        }

        /* PROFILE ICON */
        .profile-icon {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: var(--accent-primary);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            user-select: none;
            transition: all 0.2s;
        }
        .profile-icon:hover {
            opacity: 0.8;
            transform: scale(1.05);
        }

        /* Question Toggle Button */
        #questionToggleBtn {
            font-size: 1.5rem;
            background: none;
            border: none;
            color: var(--text-primary);
            cursor: pointer;
            padding: 0.5rem;
            border-radius: 8px;
            transition: color 0.2s, background 0.2s;
        }
        #questionToggleBtn:hover {
            color: var(--accent-primary);
            background: var(--bg-tertiary);
        }


        /* PROFILE MODAL */
        .profile-modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.4);
            z-index: 1000;
        }
        .profile-modal {
            position: fixed;
            top: 70px; 
            right: 1.5rem;
            width: 320px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            box-shadow: var(--shadow-lg);
            z-index: 1001;
            display: flex;
            flex-direction: column;
            animation: fadeInModal 0.2s ease-out;
            max-height: 90vh;
            overflow-y: auto;
        }
        @keyframes fadeInModal {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .modal-close-btn {
            position: absolute;
            top: 12px;
            right: 12px;
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0.25rem;
            line-height: 1;
        }
        .modal-close-btn:hover {
            color: var(--text-primary);
        }
        .modal-header {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }
        .modal-avatar {
            width: 64px;
            height: 64px;
            border-radius: 50%;
            background: var(--accent-primary);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }
        .modal-username {
            font-size: 1.125rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.25rem;
        }
        .modal-email {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }
        .modal-body {
            display: flex;
            flex-direction: column;
            padding: 0.75rem;
        }
        
        /* NEW: Profile Form Styles */
        .profile-form-group {
            margin-bottom: 1.2rem;
            padding: 0 0.75rem;
        }
        .profile-form-label {
            display: block;
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
        }
        .profile-form-input {
            width: 100%;
            padding: 0.75rem 1rem;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 0.9375rem;
            transition: all 0.2s;
        }
        .profile-form-input:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1);
        }
        #saveProfileBtn {
            width: 90%;
            margin: 0.75rem auto 1.5rem auto;
            padding: 0.75rem;
            background: var(--accent-primary);
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        #saveProfileBtn:hover {
            background: var(--accent-hover);
        }
        .profile-status {
             padding: 0.5rem 0.75rem;
             color: #38f9d7;
             font-size: 0.875rem;
             text-align: center;
        }
        
        /* Chat Container (Flex column layout) */
        .chat-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden; 
            position: relative;
        }

        /* Message Wrapper (The actual scroll area) */
        .messages-wrapper {
            flex: 1;
            overflow-y: auto; 
            padding: 2rem 1rem;
            scroll-behavior: smooth;
            transition: padding-right 0.3s ease; 
        }

        .messages-wrapper.bar-active {
             padding-right: calc(1rem + var(--question-bar-width) + 10px); 
        }
        
        .messages-wrapper::-webkit-scrollbar {
            width: 6px;
        }

        .messages-wrapper::-webkit-scrollbar-track {
            background: transparent;
        }

        .messages-wrapper::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 3px;
        }

        .messages-container {
            max-width: 800px;
            margin: 0 auto;
            width: 100%;
        }

        /* NEW: Daily Advisory Card */
        .daily-advisory-card {
            background: var(--advisory-bg);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.5);
            animation: fadeIn 0.5s ease-out;
            color: var(--advisory-text);
        }
        
        .advisory-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding-bottom: 0.75rem;
        }
        .advisory-header i {
            font-size: 1.75rem;
            color: var(--accent-primary);
        }
        .advisory-header h3 {
            font-size: 1.25rem;
            font-weight: 600;
            color: white;
            margin: 0;
        }
        .advisory-content {
            font-size: 1rem;
            line-height: 1.5;
            white-space: pre-wrap;
        }
        
        .advisory-content p { margin-bottom: 0.75rem; }
        .advisory-content ul { 
            margin-left: 1.25rem; 
            padding: 0;
        }
        .advisory-content ul li { margin-bottom: 0.5rem; }
        /* End of Daily Advisory Card */

        /* Welcome Screen */
        .welcome-screen {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100%;
            padding: 2rem;
        }

        .welcome-logo {
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, var(--accent-primary) 0%, #059669 100%);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.5rem;
            margin-bottom: 1.5rem;
            animation: fadeInScale 0.5s ease-out;
        }

        @keyframes fadeInScale {
            from {
                opacity: 0;
                transform: scale(0.9);
            }
            to {
                opacity: 1;
                transform: scale(1);
            }
        }

        .welcome-title {
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--text-secondary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .welcome-subtitle {
            font-size: 1rem;
            color: var(--text-secondary);
            margin-bottom: 3rem;
            text-align: center;
        }

        .feature-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            width: 100%;
            max-width: 900px;
        }

        .feature-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .feature-card:hover {
            background: var(--bg-tertiary);
            border-color: var(--accent-primary);
            transform: translateY(-4px);
        }

        .feature-icon {
            width: 64px;
            height: 64px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 1rem;
            overflow: hidden;
            box-shadow: var(--shadow-md);
        }

        .feature-icon img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .icon-chat { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .icon-crop { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        .icon-weather { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
        .icon-price { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }
        .icon-scheme { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); }
        
        .feature-title {
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
        }

        .feature-desc {
            font-size: 0.875rem;
            color: var(--text-secondary);
            line-height: 1.4;
        }

        /* Messages */
        .message {
            display: flex;
            gap: 1rem;
            margin-bottom: 2rem;
            animation: messageSlideIn 0.3s ease-out;
        }

        @keyframes messageSlideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .message-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
            font-weight: 600;
        }

        .user-avatar {
            background: var(--user-bg);
            color: white;
        }

        .ai-avatar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .message-content {
            flex: 1;
            line-height: 1.6;
            color: var(--text-primary);
            white-space: pre-wrap; 
        }
        
        .message-content table {
            border-collapse: collapse;
            margin: 1rem 0;
            width: 100%;
            font-size: 0.9rem;
        }
        .message-content th, .message-content td {
            border: 1px solid var(--border-color);
            padding: 0.5rem 0.75rem;
            text-align: left;
        }
        .message-content th {
            background: var(--bg-tertiary);
            color: var(--text-primary);
        }
        .message-content tr:nth-child(even) {
            background: var(--bg-secondary);
        }
        .message-content a {
            color: var(--accent-primary);
            text-decoration: none;
        }
        .message-content a:hover {
            text-decoration: underline;
        }
        
        /* Suggested Questions Section */
        #suggestedQuestions {
            margin-top: 1rem;
            padding-top: 1rem;
            border-top: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .suggestion-title {
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 500;
        }
        .suggestion-list {
            list-style: none;
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
        }
        .suggestion-list li {
            padding: 0.5rem 1rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            color: var(--text-primary);
            font-size: 0.875rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        .suggestion-list li:hover {
            background: var(--accent-primary);
            color: white;
            border-color: var(--accent-primary);
        }


        .message.user .message-content {
            background: var(--user-bg);
            padding: 1rem 1.25rem;
            border-radius: 1rem 1rem 0.25rem 1rem;
            color: white;
            white-space: normal;
            width: fit-content;
            max-width: 90%; 
        }

        .message.ai .message-content {
            color: var(--text-primary);
            white-space: normal; 
        }

        /* Input Area */
        .input-area {
            padding: 1.5rem;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
            transition: padding-right 0.3s ease; 
            flex-shrink: 0; 
        }
        
        .input-area.bar-active {
            padding-right: calc(1.5rem + var(--question-bar-width) + 10px);
        }

        .input-container {
            max-width: 800px;
            margin: 0 auto;
        }

        .input-wrapper {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 0.75rem 1rem;
            transition: all 0.2s;
        }

        .input-wrapper:focus-within {
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1);
        }

        .message-input {
            flex: 1;
            background: transparent;
            border: none;
            color: var(--text-primary);
            font-size: 0.9375rem;
            outline: none;
        }

        .message-input::placeholder {
            color: var(--text-tertiary);
        }

        .input-actions {
            display: flex;
            gap: 0.5rem;
        }

        .action-btn {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 1.125rem;
        }

        .action-btn:hover {
            background: var(--bg-hover);
            color: var(--text-primary);
        }

        .action-btn.recording {
            background: #ef4444;
            color: white;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }

        .send-btn {
            background: var(--accent-primary);
            color: white;
        }

        .send-btn:hover {
            background: var(--accent-hover);
        }

        .send-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Audio Controls */
        .audio-controls {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.75rem;
            padding: 1rem;
            margin: 1rem auto;
            max-width: 300px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
        }

        .audio-btn {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 1.125rem;
        }

        .audio-btn.play {
            background: var(--accent-primary);
            color: white;
        }

        .audio-btn.stop {
            background: #ef4444;
            color: white;
        }

        .audio-btn.download {
            background: #3b82f6;
            color: white;
        }

        .audio-btn:hover {
            transform: scale(1.05);
        }

        /* Status Bar */
        .status-bar {
            text-align: center;
            padding: 0.75rem;
            color: var(--text-secondary);
            font-size: 0.875rem;
            flex-shrink: 0;
        }

        .loading-dots {
            display: inline-flex;
            gap: 0.25rem;
        }

        .loading-dots span {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--text-secondary);
            animation: bounce 1.4s infinite ease-in-out both;
        }

        .loading-dots span:nth-child(1) { animation-delay: -0.32s; }
        .loading-dots span:nth-child(2) { animation-delay: -0.16s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }

        /* Upload Area */
        .upload-area {
            max-width: 600px;
            margin: 2rem auto;
            padding: 3rem 2rem;
            background: var(--bg-secondary);
            border: 2px dashed var(--border-color);
            border-radius: 16px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
        }

        .upload-area:hover {
            border-color: var(--accent-primary);
            background: var(--bg-tertiary);
        }

        .upload-icon {
            font-size: 3rem;
            color: var(--accent-primary);
            margin-bottom: 1rem;
        }

        .upload-text {
            font-size: 1.125rem;
            font-weight: 500;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
        }

        .upload-subtext {
            font-size: 0.875rem;
            color: var(--text-secondary);
        }

        /* Utility Classes */
        .hidden {
            display: none !important;
        }

        /* Responsive */
        @media (max-width: 768px) {
            .sidebar {
                position: fixed;
                left: 0;
                top: 0;
                height: 100vh;
                transform: translateX(-100%);
            }

            .sidebar.active {
                transform: translateX(0);
            }

            .menu-toggle {
                display: block;
            }

            .welcome-title {
                font-size: 1.5rem;
            }

            .feature-grid {
                grid-template-columns: 1fr;
            }

            .messages-wrapper {
                padding: 1rem 0.5rem;
            }
            
            .profile-modal {
                right: 1rem;
                width: calc(100% - 2rem);
            }
            
            .agri-question-bar { 
                display: none; 
            }
            .messages-wrapper.bar-active, .input-area.bar-active {
                padding-right: 1.5rem;
            }
        }

        /* Overlay for mobile sidebar */
        .overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            z-index: 99;
        }

        .overlay.active {
            display: block;
        }
        
        /* === CSS FOR QUESTION BAR TOGGLE === */
        .agri-question-bar {
            position: fixed;
            top: 70px;
            right: 0;
            width: var(--question-bar-width);
            max-height: 80vh;
            background: rgba(23, 23, 23, 0.97);
            border-left: 2px solid var(--accent-primary);
            box-shadow: -4px 0 12px rgba(16, 185, 129, 0.08);
            z-index: 105;
            overflow-y: auto;
            border-radius: 12px 0 0 12px;
            transform: translateX(var(--question-bar-width)); 
            transition: transform 0.3s cubic-bezier(0.4,0,0.2,1);
        }
        
        .agri-question-bar.active {
            transform: translateX(0);
        }

        .agri-title {
            color: var(--accent-primary);
            font-size: 1.16rem;
            letter-spacing: 0.05rem;
            padding: 0.8rem 1.1rem 0 1.1rem;
            font-weight: 600;
            text-align: left;
            margin-bottom: 0.2rem;
        }

        .agri-question-list {
            list-style: none;
            margin: 0;
            padding: 0 1.1rem 1.1rem 1.1rem;
        }

        .agri-question-list li {
            padding: 0.7rem 0.6rem;
            margin-bottom: 0.25rem;
            background: rgba(16,185,129,0.07);
            color: var(--text-primary);
            font-size: 1rem;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.23s, color 0.23s;
        }

        .agri-question-list li:hover {
            background: var(--accent-primary);
            color: var(--bg-primary);
            font-weight: 500;
        }
        /* === END CSS FOR QUESTION BAR TOGGLE === */
    </style>
</head>
<body onload="loadDailyAdvisory()">
    <div class="app-container">
        <div class="overlay" id="overlay"></div>
            
        <aside class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <div class="logo">
                    <div class="logo-icon">🌾</div>
                    <span>Grama Vaani</span>
                </div>
            </div>
                
            <button class="new-chat-btn" id="newChatBtn">
                <i class="bi bi-plus-lg"></i>
                <span>New conversation</span>
            </button>
            
            <div class="sidebar-divider">History</div>
            <div class="nav-section" id="chatHistoryList" style="flex-grow: 10; padding-top: 0.25rem;">
                </div>

            <div class="sidebar-divider">Tools</div>
            <div class="nav-section" id="toolsNav" style="flex-grow: 1; padding-top: 0.25rem;">
                <div class="nav-item" data-view="chat">
                    <i class="bi bi-robot"></i>
                    <span>AI Assistant</span>
                </div>
                <div class="nav-item" data-view="crop">
                    <i class="bi bi-flower2"></i>
                    <span>Crop Analysis</span>
                </div>
                <div class="nav-item" data-view="weather">
                    <i class="bi bi-cloud-sun"></i>
                    <span>Weather Forecast</span>
                </div>
                <div class="nav-item" data-view="price">
                    <i class="bi bi-graph-up-arrow"></i>
                    <span>Price Predictor</span>
                </div>
                <div class="nav-item" data-view="scheme">
                    <i class="bi bi-file-earmark-text"></i>
                    <span>Govt. Schemes</span>
                </div>
            </div>
            
            <div class="logout-btn" id="logoutBtn">
                <i class="bi bi-box-arrow-left"></i>
                <span>Log Out</span>
            </div>
        </aside>
        <main class="main-content">
            <header class="header">
                <div class="header-left">
                    <button class="menu-toggle" id="menuToggle">
                        <i class="bi bi-list"></i>
                    </button>
                    <div class="view-title" id="viewTitle">AI Assistant</div>
                </div>
                <div class="header-right">
                    <button id="questionToggleBtn" title="Toggle Farming Questions">
                        <i class="bi bi-question-circle"></i>
                    </button>
                    <select class="language-selector" id="languageSelect">
                        <option value="en-US">English</option>
                        <option value="hi-IN">हिन्दी</option>
                        <option value="ta-IN">தமிழ்</option>
                        <option value="te-IN">తెలుగు</option>
                        <option value="kn-IN">ಕನ್ನಡ</option>
                        <option value="ml-IN">മലയാളം</option>
                    </select>
                    <div class="profile-icon" id="profileIcon">
                        <span>{{USER_INITIAL}}</span>
                    </div>
                </div>
            </header>
            <div id="chatView" class="chat-container">
                <div class="messages-wrapper" id="messagesWrapperChat">
                    <div class="messages-container" id="chatMessages">
                        <div id="dailyAdvisoryContainer" class="messages-container" style="max-width: 800px; margin: 0 auto;">
                            </div>
                        
                        <div class="welcome-screen" id="welcomeScreen">
                            <div class="welcome-logo">🌾</div>
                            <h1 class="welcome-title">Welcome to Grama Vaani</h1>
                            <p class="welcome-subtitle">Your AI-powered farming assistant</p>
                            <div class="feature-grid">
                                <div class="feature-card" data-action="chat">
                                    <div class="feature-icon icon-chat">
                                        <img src="https://images.unsplash.com/photo-1531746790731-6c087fecd65a?w=200&h=200&fit=crop" alt="AI Assistant">
                                    </div>
                                    <div class="feature-title">AI Assistant</div>
                                    <div class="feature-desc">Get instant farming advice</div>
                                </div>
                                <div class="feature-card" data-action="crop">
                                    <div class="feature-icon icon-crop">
                                        <img src="https://images.unsplash.com/photo-1574943320219-553eb213f72d?w=200&h=200&fit=crop" alt="Crop Analysis">
                                    </div>
                                    <div class="feature-title">Crop Analysis</div>
                                    <div class="feature-desc">Detect pests & diseases</div>
                                </div>
                                <div class="feature-card" data-action="weather">
                                    <div class="feature-icon icon-weather">
                                        <img src="https://images.unsplash.com/photo-1592210454359-9043f067919b?w=200&h=200&fit=crop" alt="Weather">
                                    </div>
                                    <div class="feature-title">Weather</div>
                                    <div class="feature-desc">7-day forecast</div>
                                </div>
                                <div class="feature-card" data-action="price">
                                    <div class="feature-icon icon-price">
                                        <img src="https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=200&h=200&fit=crop" alt="Price Trends">
                                    </div>
                                    <div class="feature-title">Price Trends</div>
                                    <div class="feature-desc">Market predictions</div>
                                </div>
                                <div class="feature-card" data-action="scheme">
                                    <div class="feature-icon icon-scheme">
                                        <img src="https://images.unsplash.com/photo-1450101499163-c8848c66ca85?w=200&h=200&fit=crop" alt="Govt Schemes">
                                    </div>
                                    <div class="feature-title">Govt. Schemes</div>
                                    <div class="feature-desc">Subsidies & support</div>
                                </div>
                            </div>
                        </div>
                        </div>
                </div>
                <div class="status-bar" id="statusBar"></div>
                <div id="audioControls" class="audio-controls hidden">
                    <button class="audio-btn play" id="playBtn">
                        <i class="bi bi-play-fill"></i>
                    </button>
                    <button class="audio-btn stop" id="stopBtn">
                        <i class="bi bi-stop-fill"></i>
                    </button>
                    <button class="audio-btn download" id="downloadBtn">
                        <i class="bi bi-download"></i>
                    </button>
                </div>
                <div class="input-area" id="mainInputArea">
                    <div class="input-container">
                        <div class="input-wrapper">
                            <input type="text" class="message-input" id="messageInput" placeholder="Ask about farming, weather, prices...">
                            <div class="input-actions">
                                <button class="action-btn" id="pdfBtn" title="Download Chat as PDF">
                                    <i class="bi bi-file-earmark-arrow-down"></i>
                                </button>
                                <button class="action-btn" id="micBtn" title="Use Voice">
                                    <i class="bi bi-mic"></i>
                                </button>
                                <button class="action-btn send-btn" id="sendBtn" title="Send">
                                    <i class="bi bi-send-fill"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div id="cropView" class="chat-container hidden">
                <div class="messages-wrapper">
                    <div class="messages-container">
                        <div class="upload-area" id="uploadArea">
                            <input type="file" id="cropImageUpload" accept="image/*" class="hidden">
                            <i class="bi bi-cloud-upload upload-icon"></i>
                            <div class="upload-text">Upload Crop Image</div>
                            <div class="upload-subtext">Click or drag to analyze for pests and diseases</div>
                        </div>
                        <div id="cropResult"></div>
                    </div>
                </div>
            </div>
            <div id="weatherView" class="chat-container hidden">
                <div class="messages-wrapper">
                    <div class="messages-container">
                        <div style="max-width: 600px; margin: 2rem auto;">
                            <div class="input-wrapper">
                                <input type="text" class="message-input" id="cityInput" placeholder="Enter city name...">
                                <div class="input-actions">
                                    <button class="action-btn send-btn" id="getWeatherBtn">
                                        <i class="bi bi-search"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div id="weatherResult"></div>
                    </div>
                </div>
            </div>
            <div id="priceView" class="chat-container hidden">
                <div class="messages-wrapper">
                    <div class="messages-container">
                        <div style="max-width: 600px; margin: 2rem auto;">
                            <div class="input-wrapper">
                                <input type="text" class="message-input" id="priceInput" placeholder="e.g., Tomato price in Coimbatore">
                                <div class="input-actions">
                                    <button class="action-btn send-btn" id="getPriceBtn">
                                        <i class="bi bi-search"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div id="priceResult"></div>
                    </div>
                </div>
            </div>
            <div id="schemeView" class="chat-container hidden">
                <div class="messages-wrapper">
                    <div class="messages-container">
                        <div style="max-width: 600px; margin: 2rem auto;">
                            <div class="input-wrapper">
                                <input type="text" class="message-input" id="schemeInput" placeholder="e.g., I have 3 acres, what subsidy?">
                                <div class="input-actions">
                                    <button class="action-btn send-btn" id="getSchemeBtn">
                                        <i class="bi bi-search"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        <div id="schemeResult"></div>
                    </div>
                </div>
            </div>
        </main>
    </div>
    
    <div class="profile-modal-overlay hidden" id="profileModalOverlay"></div>
    <div class="profile-modal hidden" id="profileModal">
        <button class="modal-close-btn" id="modalCloseBtn">&times;</button>
        <div class="modal-header">
            <div class="modal-avatar">
                <span>{{USER_INITIAL}}</span>
            </div>
            <div class="modal-username">Hi, {{USER_NAME}}!</div>
            <div class="modal-email">{{USER_EMAIL}}</div>
        </div>
        <form id="profileForm">
            <div class="profile-status" id="profileStatus"></div>
            <div class="profile-form-group">
                <label class="profile-form-label" for="profileName">Name</label>
                <input type="text" id="profileName" class="profile-form-input" value="{{USER_NAME}}" required>
            </div>
            <div class="profile-form-group">
                <label class="profile-form-label" for="profilePhone">Phone</label>
                <input type="tel" id="profilePhone" class="profile-form-input" value="{{USER_PHONE}}" required>
            </div>
            <div class="profile-form-group">
                <label class="profile-form-label" for="profileLocation">Location (Village/City/State)</label>
                <input type="text" id="profileLocation" class="profile-form-input" value="{{USER_LOCATION}}" placeholder="e.g., Coimbatore, Tamil Nadu">
            </div>
            <div class="profile-form-group">
                <label class="profile-form-label" for="profileCrop">Preferred Crop</label>
                <input type="text" id="profileCrop" class="profile-form-input" value="{{USER_CROP}}" placeholder="e.g., Paddy, Sugarcane, Tomato">
            </div>
            
            <button type="submit" id="saveProfileBtn">Save Profile</button>
        </form>
        <div class="modal-body">
            </div>
    </div>
    <div id="agri-question-bar" class="agri-question-bar">
        <h4 class="agri-title">Popular Questions</h4>
        <ul class="agri-question-list">
            <li data-question="What are Kharif crops?">What are Kharif crops?</li>
            <li data-question="Suggest methods to improve soil fertility.">Methods to improve soil fertility</li>
            <li data-question="Explain drip irrigation and its benefits.">Drip irrigation and benefits</li>
            <li data-question="How to control pests in paddy fields?">Pest control in paddy fields</li>
            <li data-question="What is organic farming?">What is organic farming?</li>
            <li data-question="Best fertilizers for wheat crop">Best fertilizers for wheat</li>
            <li data-question="How does crop rotation help the soil?">Crop rotation benefits</li>
            <li data-question="What are Rabi crops with examples?">Rabi crops and examples</li>
            <li data-question="What are GMOs in agriculture?">What are GMOs?</li>
            <li data-question="How to increase yield in rice farming?">Increase rice yield</li>
        </ul>
    </div>
    
    <div class="messages-container" id="suggestedQuestionsContainer" style="display: none; padding-bottom: 3rem;">
        <div id="suggestedQuestions" style="margin: 0 auto; width: 100%; max-width: 800px;">
            </div>
    </div>

    
    <script>
        // Global variables
        let currentView = 'chat';
        let isRecording = false;
        let recognition;
        let currentAudio = null;
        let currentAudioDataUrl = null;
        let hasMessages = false;
        let currentMicButton = null;
        let currentInputElement = null;
        let isQuestionBarActive = false;
        
        // Chat History State
        let currentChatId = null;
        let currentMessages = [];

        // DOM Elements
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('overlay');
        const menuToggle = document.getElementById('menuToggle');
        const viewTitle = document.getElementById('viewTitle');
        const languageSelect = document.getElementById('languageSelect');
        const chatMessages = document.getElementById('chatMessages');
        const messagesWrapperChat = document.getElementById('messagesWrapperChat');
        const welcomeScreen = document.getElementById('welcomeScreen');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const micBtn = document.getElementById('micBtn');
        
        const pdfBtn = document.getElementById('pdfBtn');

        const statusBar = document.getElementById('statusBar');
        const audioControls = document.getElementById('audioControls');
        const playBtn = document.getElementById('playBtn');
        const stopBtn = document.getElementById('stopBtn');
        const downloadBtn = document.getElementById('downloadBtn');
        const newChatBtn = document.getElementById('newChatBtn');
        const logoutBtn = document.getElementById('logoutBtn'); 
        
        const chatHistoryList = document.getElementById('chatHistoryList');
        
        const dailyAdvisoryContainer = document.getElementById('dailyAdvisoryContainer');

        // Profile Modal DOM Elements
        const profileIcon = document.getElementById('profileIcon');
        const profileModal = document.getElementById('profileModal');
        const profileModalOverlay = document.getElementById('profileModalOverlay');
        const modalCloseBtn = document.getElementById('modalCloseBtn');
        const profileForm = document.getElementById('profileForm');
        const profileNameInput = document.getElementById('profileName');
        const profilePhoneInput = document.getElementById('profilePhone');
        const profileLocationInput = document.getElementById('profileLocation');
        const profileCropInput = document.getElementById('profileCrop');
        const profileStatusDiv = document.getElementById('profileStatus');

        // Other View Elements
        const uploadArea = document.getElementById('uploadArea');
        const cropImageUpload = document.getElementById('cropImageUpload');
        const cropResult = document.getElementById('cropResult');
        
        const cityInput = document.getElementById('cityInput');
        const getWeatherBtn = document.getElementById('getWeatherBtn');
        const weatherResult = document.getElementById('weatherResult');

        const priceInput = document.getElementById('priceInput');
        const getPriceBtn = document.getElementById('getPriceBtn');
        const priceResult = document.getElementById('priceResult');

        const schemeInput = document.getElementById('schemeInput');
        const getSchemeBtn = document.getElementById('getSchemeBtn');
        const schemeResult = document.getElementById('schemeResult');
        
        const agriQuestionBar = document.getElementById('agri-question-bar');
        const agriQuestionList = document.querySelector('#agri-question-bar .agri-question-list');
        const questionToggleBtn = document.getElementById('questionToggleBtn');
        const inputArea = document.getElementById('mainInputArea'); 
        
        const suggestedQuestionsContainer = document.getElementById('suggestedQuestionsContainer');
        const suggestedQuestionsInner = document.getElementById('suggestedQuestions');


        // Views
        const views = {
            'chat': document.getElementById('chatView'),
            'crop': document.getElementById('cropView'),
            'weather': document.getElementById('weatherView'),
            'price': document.getElementById('priceView'),
            'scheme': document.getElementById('schemeView')
        };
        
        const allMessagesWrappers = document.querySelectorAll('.messages-wrapper');

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initSpeechRecognition();
            attachEventListeners();
            loadChatHistory(); 
            document.querySelector('.nav-item[data-view="chat"]').classList.add('active'); 
            switchView('chat', 'AI Assistant'); 
        });

        // Secure Fetch Wrapper
        async function secureFetch(url, options) {
            const response = await fetch(url, options);
            if (response.status === 401) {
                alert("Your session has expired. Please log in again.");
                handleLogout(); 
                return null;
            }
            return response;
        }
        
        // *** NEW: Load Daily Advisory ***
        async function loadDailyAdvisory() {
            if (currentView !== 'chat') return; 

            dailyAdvisoryContainer.innerHTML = `
                <div class="daily-advisory-card">
                    <div class="advisory-header">
                        <i class="bi bi-geo-alt-fill"></i>
                        <h3>Daily Advisory</h3>
                    </div>
                    <div class="advisory-content">
                        <p>Loading your personalized farming advisory... <div class="loading-dots" style="display: inline-flex; vertical-align: middle;"><span></span><span></span><span></span></div></p>
                    </div>
                </div>
            `;
            
            try {
                const response = await secureFetch('/advisory');
                if (!response) {
                    dailyAdvisoryContainer.innerHTML = ''; 
                    return; 
                }
                
                const data = await response.json();
                
                if (data.text) {
                    const htmlContent = window.marked.parse(data.text);
                    
                    dailyAdvisoryContainer.innerHTML = `
                        <div class="daily-advisory-card">
                            <div class="advisory-header">
                                <i class="bi bi-geo-alt-fill"></i>
                                <h3>Daily Advisory</h3>
                                <p style="font-size: 0.8rem; color: var(--advisory-text); margin: 0 0 0 auto;">Location: ${profileLocationInput.value || 'Not Set'} | Crop: ${profileCropInput.value || 'Not Set'}</p>
                            </div>
                            <div class="advisory-content">
                                ${htmlContent}
                            </div>
                        </div>
                    `;
                    
                    if (data.audio) {
                         playAudio(data.audio);
                    }
                } else {
                    dailyAdvisoryContainer.innerHTML = '';
                }
                
            } catch (err) {
                console.error('Advisory Load Error:', err);
                dailyAdvisoryContainer.innerHTML = `<p style="text-align: center; color: var(--text-secondary);">Could not load daily advisory. Please check your profile settings.</p>`;
            }
        }
        // *** END NEW: Load Daily Advisory ***
        
        function initSpeechRecognition() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (SpeechRecognition) {
                recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = languageSelect.value;
                recognition.onresult = (event) => {
                    const transcript = event.results[0][0].transcript;
                    if (currentInputElement) {
                        currentInputElement.value = transcript;
                        if (currentInputElement === messageInput) {
                            handleSend();
                        }
                    }
                    stopRecording();
                };
                recognition.onstart = () => {
                    isRecording = true;
                    showStatus("Listening...");
                    if(currentMicButton) {
                        currentMicButton.classList.add('recording');
                    }
                };
                recognition.onend = () => {
                    stopRecording();
                };
                recognition.onerror = (event) => {
                    showStatus(`Error: ${event.error}`, false);
                    setTimeout(hideStatus, 3000); 
                    stopRecording();
                };
            } else {
                showStatus("Speech recognition not supported in this browser.", false);
                [micBtn].forEach(btn => btn.disabled = true);
            }
        }

        function startRecording(inputElement, micButton) {
            if (isRecording) {
                stopRecording();
                return;
            }
            if (recognition) {
                currentInputElement = inputElement;
                currentMicButton = micButton;
                recognition.lang = languageSelect.value;
                recognition.start();
            }
        }

        function stopRecording() {
            if (recognition && isRecording) {
                recognition.stop();
            }
            isRecording = false;
            if(currentMicButton) {
                currentMicButton.classList.remove('recording');
            }
        }

        function attachEventListeners() {
            document.querySelectorAll('#toolsNav .nav-item').forEach(item => {
                item.addEventListener('click', () => {
                    const view = item.dataset.view;
                    const title = item.textContent.trim();
                    
                    highlightActiveChat(null); 
                    document.querySelectorAll('#toolsNav .nav-item').forEach(n => n.classList.remove('active'));
                    item.classList.add('active');

                    switchView(view, title);
                    
                });
            });

            document.querySelectorAll('.feature-card').forEach(card => {
                card.addEventListener('click', () => {
                    const action = card.dataset.action;
                    if (action === 'chat') {
                        switchView('chat', 'AI Assistant');
                        messageInput.focus();
                    } else {
                        const navItem = document.querySelector(`#toolsNav .nav-item[data-view="${action}"]`);
                        if(navItem) {
                            navItem.click();
                        }
                    }
                });
            });

            // Mobile Menu
            menuToggle.addEventListener('click', () => {
                sidebar.classList.toggle('active');
                overlay.classList.toggle('active');
            });

            overlay.addEventListener('click', () => {
                sidebar.classList.remove('active');
                overlay.classList.remove('active');
            });

            newChatBtn.addEventListener('click', clearChat);
            logoutBtn.addEventListener('click', handleLogout); 

            profileIcon.addEventListener('click', () => {
                profileModal.classList.remove('hidden');
                profileModalOverlay.classList.remove('hidden');
                profileStatusDiv.textContent = ''; 
            });
            modalCloseBtn.addEventListener('click', closeProfileModal);
            profileModalOverlay.addEventListener('click', closeProfileModal);
            
            profileForm.addEventListener('submit', handleProfileUpdate);

            languageSelect.addEventListener('change', () => {
                if (recognition) {
                    recognition.lang = languageSelect.value;
                }
            });

            // Chat View
            sendBtn.addEventListener('click', handleSend);
            messageInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') handleSend();
            });
            micBtn.addEventListener('click', () => startRecording(messageInput, micBtn));

            pdfBtn.addEventListener('click', handleDownloadPDF);

            // Audio Controls
            playBtn.addEventListener('click', handlePlayAudio);
            stopBtn.addEventListener('click', handleStopAudio);
            downloadBtn.addEventListener('click', handleDownloadAudio);

            // Other Views
            uploadArea.addEventListener('click', () => cropImageUpload.click());
            cropImageUpload.addEventListener('change', handleCropUpload);
            
            getWeatherBtn.addEventListener('click', handleGetWeather);
            cityInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') handleGetWeather();
            });
            
            getPriceBtn.addEventListener('click', handleGetPrice);
            priceInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') handleGetPrice();
            });

            getSchemeBtn.addEventListener('click', handleGetScheme);
            schemeInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') handleGetScheme();
            });
            
            questionToggleBtn.addEventListener('click', toggleQuestionBar);
            
            if (agriQuestionList) {
                agriQuestionList.addEventListener('click', function (e) {
                    if (e.target.tagName === 'LI') {
                        const question = e.target.getAttribute('data-question');
                        
                        const chatNavItem = document.querySelector(`.nav-item[data-view="chat"]`);
                        if(chatNavItem) {
                            chatNavItem.click();
                        }

                        messageInput.value = question;
                        messageInput.focus();
                        toggleQuestionBar(); 
                    }
                });
            }
            
            suggestedQuestionsInner.addEventListener('click', function(e) {
                if (e.target.tagName === 'LI') {
                    const question = e.target.textContent;
                    messageInput.value = question;
                    messageInput.focus();
                    handleSend(); 
                }
            });
        }
        
        async function handleProfileUpdate(e) {
            e.preventDefault();
            
            profileStatusDiv.textContent = 'Saving...';
            profileStatusDiv.style.color = '#38f9d7';

            const payload = {
                name: profileNameInput.value.trim(),
                phone: profilePhoneInput.value.trim(),
                location: profileLocationInput.value.trim(),
                preferred_crop: profileCropInput.value.trim(),
            };
            
            try {
                const response = await secureFetch('/profile/update', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (!response) return;

                if (response.ok) {
                    profileStatusDiv.textContent = 'Profile saved successfully! Reloading advisory...';
                    document.querySelector('.modal-username').textContent = `Hi, ${payload.name}!`;
                    document.querySelector('.profile-icon span').textContent = payload.name[0].toUpperCase();
                    
                    await loadDailyAdvisory();
                    
                    setTimeout(() => {
                        profileStatusDiv.textContent = '';
                        closeProfileModal();
                    }, 2000);

                } else {
                    const data = await response.json();
                    profileStatusDiv.textContent = data.detail || 'Failed to save profile.';
                    profileStatusDiv.style.color = '#ef4444';
                }
            } catch (err) {
                console.error('Profile Update Error:', err);
                profileStatusDiv.textContent = 'An error occurred during save.';
                profileStatusDiv.style.color = '#ef4444';
            }
        }


        function toggleQuestionBar() {
            if (window.innerWidth <= 768) return;

            isQuestionBarActive = !isQuestionBarActive;
            
            agriQuestionBar.classList.toggle('active', isQuestionBarActive);
            agriQuestionBar.classList.remove('hidden'); 

            const shouldBeBarActive = isQuestionBarActive && currentView === 'chat';
            messagesWrapperChat.classList.toggle('bar-active', shouldBeBarActive);
            inputArea.classList.toggle('bar-active', shouldBeBarActive);
            
            if(isQuestionBarActive && currentView !== 'chat') {
                const chatNavItem = document.querySelector('.nav-item[data-view="chat"]');
                if(chatNavItem) {
                    chatNavItem.click();
                }
            }
        }
        
        function closeProfileModal() {
            profileModal.classList.add('hidden');
            profileModalOverlay.classList.add('hidden');
        }
        
        function handleDownloadPDF() {
            if (currentMessages.length === 0) {
                alert("Chat is empty. Nothing to download.");
                return;
            }

            const { jsPDF } = window.jspdf;
            const doc = new jsPDF();
            
            let yPosition = 20; 
            const leftMargin = 15;
            const maxWidth = 180; 

            doc.setFontSize(18);
            doc.setFont("helvetica", "bold");
            doc.text("Grama Vaani - Chat Report", leftMargin, yPosition);
            yPosition += 10;
            
            doc.setFontSize(10);
            doc.setFont("helvetica", "normal");
            doc.text(`Report generated on: ${new Date().toLocaleString()}`, leftMargin, yPosition);
            yPosition += 15;

            doc.setFontSize(12);
            
            currentMessages.forEach(msg => {
                const prefix = msg.role === 'user' ? "You: " : "AI: ";
                
                let text = msg.text;
                if (msg.role === 'ai') {
                    text = text.replace(/\[(.*?)\]\((.*?)\)/g, '$1 ($2)');
                    text = text.replace(/\|.*?\|/g, ' '); 
                    text = text.replace(/[*#]/g, ''); 
                }
                
                const combinedText = prefix + text;
                
                doc.setFont("helvetica", msg.role === 'user' ? "bold" : "normal");

                const lines = doc.splitTextToSize(combinedText, maxWidth);
                
                if (yPosition + (lines.length * 7) > 280) { 
                    doc.addPage();
                    yPosition = 20; 
                }

                doc.text(lines, leftMargin, yPosition);
                yPosition += (lines.length * 7) + 10; 
            });

            doc.save(`Grama-Vaani-Chat-Report-${new Date().toISOString().slice(0, 10)}.pdf`);
        }


        async function handleLogout() {
            try {
                await fetch('/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
            } catch (err) {
                console.error("Logout request failed:", err);
            } finally {
                window.location.href = '/';
            }
        }

        function switchView(viewName, title) {
            currentView = viewName;
            
            Object.values(views).forEach(view => view.classList.add('hidden'));
            
            if (views[viewName]) {
                views[viewName].classList.remove('hidden');
            }
            
            viewTitle.textContent = title;
            
            const shouldBeBarActive = isQuestionBarActive && viewName === 'chat' && window.innerWidth > 768;
            messagesWrapperChat.classList.toggle('bar-active', shouldBeBarActive);
            inputArea.classList.toggle('bar-active', shouldBeBarActive);
            
            if (viewName !== 'chat') {
                 suggestedQuestionsContainer.style.display = 'none';
                 highlightActiveChat(null, true);
            } else {
                 if (currentMessages.length > 0) {
                     getSuggestedQuestions();
                 } else {
                     suggestedQuestionsContainer.style.display = 'none';
                     loadDailyAdvisory();
                 }
                 highlightActiveChat(currentChatId || null, true); 
            }

            sidebar.classList.remove('active');
            overlay.classList.remove('active');
            handleStopAudio();
            hideAudioControls();
        }

        function clearChat() {
            currentChatId = null;
            currentMessages = [];
            chatMessages.innerHTML = '';
            chatMessages.appendChild(dailyAdvisoryContainer); 
            chatMessages.appendChild(welcomeScreen); 
            welcomeScreen.classList.remove('hidden');
            hasMessages = false;
            hideAudioControls();
            hideStatus();
            suggestedQuestionsContainer.style.display = 'none';
            
            loadChatHistory();
            switchView('chat', 'AI Assistant'); 
            highlightActiveChat(null, true);
        }

        async function loadChatHistory() {
            const response = await secureFetch('/chats');
            if (!response) return;
            
            const chats = await response.json();
            chatHistoryList.innerHTML = ''; 
            
            chats.forEach(chat => {
                const button = document.createElement('button');
                button.className = 'chat-history-item';
                button.textContent = chat.title;
                button.dataset.id = chat.id;
                button.addEventListener('click', () => loadChat(chat.id));
                chatHistoryList.appendChild(button);
            });
            
            if (currentView === 'chat') {
                highlightActiveChat(currentChatId);
            }
        }
        
        async function loadChat(chatId) {
            const response = await secureFetch(`/chats/${chatId}`);
            if (!response) return;
            
            const chatData = await response.json();
            currentChatId = chatData.id;
            currentMessages = chatData.messages;
            
            chatMessages.innerHTML = ''; 
            chatMessages.appendChild(dailyAdvisoryContainer); 
            welcomeScreen.classList.add('hidden');
            hasMessages = true;
            
            currentMessages.forEach(msg => appendMessageToDOM(msg.role, msg.text));
            
            switchView('chat', 'AI Assistant'); 
            highlightActiveChat(chatId);
            
            if (currentMessages.length > 0) {
                getSuggestedQuestions();
            } else {
                suggestedQuestionsContainer.style.display = 'none';
            }
            
            scrollToBottom(messagesWrapperChat);
        }
        
        async function saveCurrentChat(isNewChat) {
            if (currentMessages.length === 0) return;
            
            try {
                const response = await secureFetch('/save_chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        chat_id: currentChatId,
                        messages: currentMessages
                    })
                });
                if (!response) return;

                const data = await response.json(); 
                const newChatId = data.chat_id;
                
                if (isNewChat) {
                    await loadChatHistory(); 
                }
                
                currentChatId = newChatId;
                highlightActiveChat(currentChatId);
                
            } catch (err) {
                console.error("Failed to save chat:", err);
            }
        }
        
        function highlightActiveChat(chatId, forceToolHighlight = false) {
             document.querySelectorAll('#toolsNav .nav-item').forEach(item => {
                 item.classList.remove('active');
             });
             document.querySelectorAll('.chat-history-item').forEach(item => {
                 item.classList.remove('active');
             });
            
             if (chatId) {
                 const activeItem = document.querySelector(`.chat-history-item[data-id="${chatId}"]`);
                 if (activeItem) {
                     activeItem.classList.add('active');
                 }
             } else if (currentView === 'chat' || forceToolHighlight) {
                  const chatNavItem = document.querySelector(`.nav-item[data-view="chat"]`);
                  if(chatNavItem) chatNavItem.classList.add('active');
             }
        }
        
        function appendMessageToDOM(role, text) {
             const messageEl = document.createElement('div');
             messageEl.classList.add('message', role); 
             
             const htmlContent = window.marked.parse(text); 

             messageEl.innerHTML = `
                 <div class="message-avatar ${role}-avatar">
                     <i class="bi bi-${role === 'user' ? 'person-fill' : 'robot'}"></i>
                 </div>
                 <div class="message-content">
                     ${htmlContent}
                 </div>
             `;
             chatMessages.appendChild(messageEl);
             scrollToBottom(messagesWrapperChat); 
        }
        
        async function getSuggestedQuestions() {
            const historyForContext = currentMessages.slice(-5); 
            
            if (currentView !== 'chat' || historyForContext.length === 0) {
                 renderSuggestedQuestions([]);
                 return;
            }

            try {
                const response = await secureFetch('/suggest_questions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        history: historyForContext,
                        language: languageSelect.value
                    })
                });
                
                if (!response) {
                    renderSuggestedQuestions([]);
                    return;
                } 
                
                const data = await response.json(); 
                renderSuggestedQuestions(data.questions || []);

            } catch (err) {
                console.error('Suggested Questions Error:', err);
                renderSuggestedQuestions([]);
            }
        }
        
        function renderSuggestedQuestions(questions) {
            const container = suggestedQuestionsContainer;
            const innerContainer = suggestedQuestionsInner;
            
            innerContainer.innerHTML = ''; 
            
            if (questions.length === 0 || currentView !== 'chat') {
                 container.style.display = 'none';
                 return;
            }
            
            container.style.display = 'block';
            
            let html = `
                <div class="suggestion-title">Would you like to ask about...</div>
                <ul class="suggestion-list">
            `;
            
            questions.forEach(q => {
                html += `<li>${q}</li>`; 
            });
            
            html += `
                </ul>
            `;
            
            innerContainer.innerHTML = html;

            if (messagesWrapperChat && container.parentElement !== messagesWrapperChat) {
                messagesWrapperChat.appendChild(container);
            }
            
            scrollToBottom(messagesWrapperChat); 
        }

        async function handleSend() {
            const query = messageInput.value.trim();
            if (query) {
                const isNewChat = (currentChatId === null);
                
                suggestedQuestionsContainer.style.display = 'none';
                
                addUserMessage(query); 
                messageInput.value = '';
                showStatus("Grama Vaani is thinking...", true);
                hideAudioControls();
                
                dailyAdvisoryContainer.innerHTML = '';


                try {
                    const response = await secureFetch('/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text: query, language: languageSelect.value })
                    });
                    
                    if (!response) return; 

                    const data = await response.json();
                    hideStatus();
                    
                    addAIMessage(data.text, data.audio);
                    
                    await saveCurrentChat(isNewChat); 
                    
                    getSuggestedQuestions(); 
                    
                } catch (err) {
                    console.error('Chat Error:', err);
                    hideStatus();
                    addAIMessage("Sorry, I couldn't connect to the server. Please try again.", null);
                }
            }
        }
        
        function addUserMessage(text) {
            if (!hasMessages) {
                welcomeScreen.classList.add('hidden');
                hasMessages = true;
            }
            hideAudioControls();

            currentMessages.push({role: 'user', text: text});
            
            const messageEl = document.createElement('div');
            messageEl.classList.add('message', 'user');
            messageEl.innerHTML = `
                <div class="message-avatar user-avatar">
                    <i class="bi bi-person-fill"></i>
                </div>
                <div class="message-content" style="white-space: pre-wrap;">
                    ${text}
                </div>
            `;
            chatMessages.appendChild(messageEl);
            
            scrollToBottom(messagesWrapperChat);
        }

        function addAIMessage(text, audioBase64) {
            currentMessages.push({role: 'ai', text: text});
            
            appendMessageToDOM('ai', text); 
            
            if (audioBase64) {
                playAudio(audioBase64);
            }
        }
        
        function addAIMessageToView(viewElement, text) {
            suggestedQuestionsContainer.style.display = 'none';
            
            const htmlContent = window.marked.parse(text); 
            viewElement.innerHTML = `
                <div class="message ai">
                    <div class="message-avatar ai-avatar">
                        <i class="bi bi-robot"></i>
                    </div>
                    <div class="message-content">
                        ${htmlContent}
                    </div>
                </div>
            `;
            const wrapper = viewElement.closest('.messages-wrapper');
            if(wrapper) scrollToBottom(wrapper);
        }

        function addLoadingMessageToView(viewElement, text) {
            viewElement.innerHTML = `
                <div class="message ai">
                    <div class="message-avatar ai-avatar">
                        <i class="bi bi-robot"></i>
                    </div>
                    <div class="message-content">
                        ${text}
                        <div class="loading-dots" style="justify-content: left; padding: 10px 0;">
                            <span></span><span></span><span></span>
                        </div>
                    </div>
                </div>
            `;
             const wrapper = viewElement.closest('.messages-wrapper');
            if(wrapper) scrollToBottom(wrapper);
        }

        function scrollToBottom(element) {
            if(element) {
                element.scrollTop = element.scrollHeight;
            }
        }

        function showStatus(message, isLoading = false) {
            if (isLoading) {
                statusBar.innerHTML = `
                    <span>${message}</span>
                    <div class="loading-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                `;
            } else {
                statusBar.innerHTML = `<span>${message}</span>`;
            }
            statusBar.classList.remove('hidden');
        }

        function hideStatus() {
            statusBar.innerHTML = '';
            statusBar.classList.add('hidden');
        }

        function showAudioControls() {
            audioControls.classList.remove('hidden');
        }

        function hideAudioControls() {
            handleStopAudio();
            audioControls.classList.add('hidden');
            currentAudio = null;
            currentAudioDataUrl = null;
        }

        function playAudio(base64Audio) {
            handleStopAudio(); 
            currentAudioDataUrl = `data:audio/mp3;base64,${base64Audio}`;
            currentAudio = new Audio(currentAudioDataUrl);
            
            currentAudio.onplay = () => {
                playBtn.innerHTML = '<i class="bi bi-pause-fill"></i>';
            };
            
            currentAudio.onpause = () => {
                playBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
            };
            
            currentAudio.onended = () => {
                playBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
                currentAudio.currentTime = 0;
            };

            currentAudio.onerror = (e) => {
                console.error("Audio playback error:", e);
            };
            
            currentAudio.play();
            showAudioControls();
        }

        function handlePlayAudio() {
            if (currentAudio) {
                if (currentAudio.paused) {
                    currentAudio.play();
                } else {
                    currentAudio.pause();
                }
            }
        }

        function handleStopAudio() {
            if (currentAudio) {
                currentAudio.pause();
                currentAudio.currentTime = 0;
            }
            playBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
        }
        
        function handleDownloadAudio() {
            if (currentAudioDataUrl) {
                const a = document.createElement('a');
                a.href = currentAudioDataUrl;
                a.download = 'grama-vaani-response.mp3';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            } else {
                alert('No audio to download.');
            }
        }

        async function handleCropUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            addLoadingMessageToView(cropResult, "Analyzing image...");
            hideAudioControls();
            
            const imageUrl = URL.createObjectURL(file);
            cropResult.innerHTML = `
                <div style="text-align: center; margin-bottom: 2rem;">
                    <img src="${imageUrl}" alt="Uploaded Crop" style="max-width: 100%; height: auto; max-height: 300px; border-radius: 8px; border: 1px solid var(--border-color);">
                </div>
            ` + cropResult.innerHTML;
            
            const formData = new FormData();
            formData.append('file', file);
            formData.append('language', languageSelect.value);

            try {
                const response = await secureFetch('/analyse-crop', {
                    method: 'POST',
                    body: formData
                });
                if (!response) return; 
                
                const data = await response.json(); 
                
                if (response.status !== 200) {
                    addAIMessageToView(cropResult, data.detail.text || "Sorry, image analysis failed.");
                    if (data.detail.audio) playAudio(data.detail.audio);
                    return;
                }

                addAIMessageToView(cropResult, data.text);
                playAudio(data.audio);
            } catch (err) {
                console.error('Crop Error:', err);
                addAIMessageToView(cropResult, "Sorry, image analysis failed due to a network or server error.");
            }
        }

        async function handleGetWeather() {
            const city = cityInput.value.trim();
            if (!city) {
                weatherResult.innerHTML = `<p style="text-align: center; color: var(--text-secondary);">Please enter a city name.</p>`;
                return;
            }
            
            addLoadingMessageToView(weatherResult, `Fetching weather for ${city}...`);
            hideAudioControls();

            try {
                const response = await secureFetch(`/weather/${encodeURIComponent(city)}?language=${languageSelect.value}`);
                if (!response) return; 

                const data = await response.json();
                addAIMessageToView(weatherResult, data.text);
                playAudio(data.audio);
            } catch (err) {
                console.error('Weather Error:', err);
                addAIMessageToView(weatherResult, "Sorry, could not fetch weather data.");
            }
        }
        
        async function handleGetPrice() {
            const query = priceInput.value.trim();
            if (!query) {
                priceResult.innerHTML = `<p style="text-align: center; color: var(--text-secondary);">Please enter a crop and market.</p>`;
                return;
            }
            
            addLoadingMessageToView(priceResult, `Fetching price trends for ${query}...`);
            hideAudioControls();

            try {
                const response = await secureFetch('/price', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: query, language: languageSelect.value })
                });
                if (!response) return; 

                const data = await response.json();
                addAIMessageToView(priceResult, data.text);
                
            } catch (err) {
                console.error('Price Error:', err);
                addAIMessageToView(priceResult, "Sorry, price forecast failed.");
            }
        }

        async function handleGetScheme() {
            const query = schemeInput.value.trim();
            if (!query) {
                schemeResult.innerHTML = `<p style="text-align: center; color: var(--text-secondary);">Please describe your needs.</p>`;
                return;
            }
            
            addLoadingMessageToView(schemeResult, `Searching for schemes related to: "${query}"...`);
            hideAudioControls();

            try {
                const response = await secureFetch('/scheme', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: query, language: languageSelect.value })
                });
                if (!response) return; 

                const data = await response.json();
                addAIMessageToView(schemeResult, data.text);

            } catch (err) {
                console.error('Scheme Error:', err);
                addAIMessageToView(schemeResult, "Sorry, scheme information failed.");
            }
        }
    </script>

</body>
</html>
"""

# --------------------------------------------------------------------------
# FASTAPI APP
# --------------------------------------------------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global clients/sessions
tts_client = None
vision_client = None
gemini_model = None
chat_session = None

@app.on_event("startup")
def startup_event():
    global tts_client, vision_client, gemini_model, chat_session
    try:
        tts_client = texttospeech.TextToSpeechClient()
        vision_client = vision.ImageAnnotatorClient()
        vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION)
        gemini_model = GenerativeModel("gemini-2.0-flash") 
        chat_session = gemini_model.start_chat()
        print("All clients initialized.")
    except Exception as e:
        print(f"STARTUP ERROR: {e}")
        raise

# --------------------------------------------------------------------------
# AUTH DEPENDENCY
# --------------------------------------------------------------------------

async def get_current_user_dependency(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        token_data = TokenData(email=email)
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    
    user_doc = users_collection.find_one({"email": token_data.email})
    if user_doc is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    # Ensure backward compatibility for new fields
    user_doc["location"] = user_doc.get("location", "India")
    user_doc["preferred_crop"] = user_doc.get("preferred_crop", "Paddy")
    
    return user_doc

# --------------------------------------------------------------------------
# CORE ASYNC FUNCTIONS (wrapped in simple sync helpers for the Python logic)
# --------------------------------------------------------------------------

async def perform_signup(user_data: UserCreate, response: Response):
    existing_user = users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user_data.password)
    user_in_db = UserInDB(
        name=user_data.name, email=user_data.email, phone=user_data.phone,
        hashed_password=hashed_password, location=user_data.location, 
        preferred_crop=user_data.preferred_crop
    )
    users_collection.insert_one(user_in_db.model_dump(by_alias=True))
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user_data.email}, expires_delta=access_token_expires)
    
    response.set_cookie(key="access_token", value=f"{access_token}", httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="Lax", path="/")
    return {"message": "Signup successful"}

async def perform_login(form_data: UserLogin, response: Response):
    user = users_collection.find_one({"email": form_data.email})
    
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user["email"]}, expires_delta=access_token_expires)
    
    response.set_cookie(key="access_token", value=f"{access_token}", httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="Lax", path="/")
    return {"message": "Login successful"}

async def perform_update_profile(user_data: UserUpdateProfile, current_user: dict):
    update_fields = user_data.model_dump(exclude_unset=True, exclude_none=True)

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    result = users_collection.update_one({"email": current_user["email"]}, {"$set": update_fields})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "Profile updated successfully", "updated_fields": update_fields}

async def handle_advisory(language: str, current_user: dict):
    location = current_user.get("location", "India")
    crop = current_user.get("preferred_crop", "Paddy")
    lang_code = language.split("-")[0]
    
    if location in ["India", "Not Set"] or crop in ["Paddy", "Not Set"]:
        text = f"Hello, {current_user.get('name', 'Farmer')}! Your profile currently uses default settings (Location: **{location}**, Crop: **{crop}**). Please update your profile for truly localized advice! Today's general advice: Check your irrigation systems and plan your next week's fertilizer application."
        
        text = translate_text(text, lang_code) if lang_code != "en" else text
        
        clean_speech_text = clean_text_for_speech(text)
        audio = text_to_speech_google(clean_speech_text, language)
        return AdvisoryResponse(text=text, audio=audio)
        
    try:
        text = get_daily_advisory(location, crop, language)
        
        clean_speech_text = clean_text_for_speech(text)
        audio = text_to_speech_google(clean_speech_text, language)
        
        return AdvisoryResponse(text=text, audio=audio)
    
    except Exception as e:
        print(f"Advisory endpoint error: {e}")
        err = "Sorry, failed to generate today's advisory due to a server error."
        err = translate_text(err, lang_code) if lang_code != "en" else err
        
        clean_speech_text = clean_text_for_speech(err)
        audio = text_to_speech_google(clean_speech_text, language)
        return AdvisoryResponse(text=err, audio=audio)

# --------------------------------------------------------------------------
# API HELPER FUNCTIONS (Sync functions used by the async handlers)
# --------------------------------------------------------------------------

def clean_text_for_speech(text: str) -> str:
    try:
        text = text.replace("°C", " degrees Celsius")
        text = text.replace("km/h", " kilometers per hour")
        text = text.replace("mm", " millimeters")
        text = text.replace("₹", " rupees ")
        text = re.sub(r'(\*\*|#|\[.*?\]\(.*?\))', ' ', text)
        text = text.replace("--------------------", " ")
        text = text.replace("|", " ")
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception as e:
        print(f"Error cleaning text: {e}")
        return text

def translate_text(text: str, target_lang_code: str) -> str:
    if target_lang_code == "en" or not gemini_model:
        return text
    try:
        prompt = f"Translate the following text concisely into language code '{target_lang_code}'. Preserve all emojis and markdown formatting but translate the prose:\n\n{text}"
        response = gemini_model.generate_content(prompt)
        clean_response = response.text.strip()
        if clean_response.startswith('"') and clean_response.endswith('"'):
            clean_response = clean_response[1:-1]
        elif clean_response.startswith('1.') or clean_response.startswith('*'):
             clean_response = re.sub(r'^[*-]?\s?\d*\.\s*', '', clean_response).strip()
             
        return clean_response
    except Exception as e:
        print(f"Translation error: {e}")
        return text

def get_weather_emoji_and_description(wmo_code: int):
    mapping = {
        0: ("☀️", "Clear sky"), (1, 2, 3): ("🌥️", "Mainly clear/Partly cloudy"),
        (45, 48): ("🌫️", "Fog"), (51, 53, 55): ("🌦️", "Drizzle"),
        (56, 57): ("🌨️", "Freezing Drizzle"), (61, 63, 65): ("🌧️", "Rain"),
        (66, 67): ("🌨️", "Freezing Rain"), (71, 73, 75): ("❄️", "Snow fall"),
        (77): ("❄️", "Snow grains"), (80, 81, 82): ("🌦️", "Rain showers"),
        (85, 86): ("🌨️", "Snow showers"), (95, 96, 99): ("⛈️", "Thunderstorm"),
    }
    for codes, (emoji, desc) in mapping.items():
        if isinstance(codes, int) and wmo_code == codes:
            return emoji, desc
        if isinstance(codes, tuple) and wmo_code in codes:
            return emoji, desc
    return "🌡️", "Unknown"

def get_weather(city: str, language: str = "en-US") -> str:
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"https://geocode.maps.co/search?q={city}")
            r.raise_for_status()
            data = r.json()
            if not data:
                return f"Could not find location: {city}"
            lat, lon = data[0]["lat"], data[0]["lon"]
            city_name = data[0]["display_name"].split(",")[0]

        params = {
            "latitude": lat, "longitude": lon,
            "current_weather": "true",
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum",
            "forecast_days": 7, "timezone": "auto"
        }
        with httpx.Client(timeout=10.0) as client:
            r = client.get("https://api.open-meteo.com/v1/forecast", params=params)
            r.raise_for_status()
            data = r.json()

        current = data["current_weather"]
        emoji, desc = get_weather_emoji_and_description(current["weathercode"])
        
        report = f"## 7-Day Weather Forecast for {city_name}\n\n"
        report += f"**Current:** {emoji} {current['temperature']}°C | {desc} | Wind: {current['windspeed']} km/h\n\n"
        
        report += "| Day | Weather | High (°C) | Low (°C) | Rain (mm) |\n"
        report += "|:---:|:---:|:---:|:---:|:---:|\n"
        
        daily = data["daily"]
        for i in range(7):
            date = daily["time"][i]
            day_name = "Today" if i == 0 else "Tomorrow" if i == 1 else datetime.fromisoformat(date).strftime("%A")
            e, d = get_weather_emoji_and_description(daily["weathercode"][i])
            
            report += (f"| {day_name} | {e} {d} | {daily['temperature_2m_max'][i]} | "
                        f"{daily['temperature_2m_min'][i]} | {daily['precipitation_sum'][i]} |\n")

        report += "\n*Data from Open-Meteo.*"

        lang_code = language.split("-")[0]
        return translate_text(report, lang_code) if lang_code != "en" else report

    except Exception as e:
        print(f"Weather error: {e}")
        return "Sorry, the external weather service could not be reached or the location was not specific enough."

def get_daily_advisory(location: str, preferred_crop: str, language: str) -> str:
    if not gemini_model:
        return "AI not ready."

    lang_code = language.split("-")[0]

    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"https://geocode.maps.co/search?q={location}")
            r.raise_for_status()
            data = r.json()
            if not data:
                weather_info = f"Weather: Location '{location}' not found."
            else:
                lat, lon = data[0]["lat"], data[0]["lon"]
                
                params = {
                    "latitude": lat, "longitude": lon,
                    "current_weather": "true",
                    "daily": "weathercode,temperature_2m_max,precipitation_sum",
                    "forecast_days": 1, "timezone": "auto"
                }
                r_weather = client.get("https://api.open-meteo.com/v1/forecast", params=params)
                r_weather.raise_for_status()
                weather_data = r_weather.json()

                current = weather_data["current_weather"]
                daily = weather_data["daily"]
                
                emoji, desc = get_weather_emoji_and_description(current["weathercode"])
                
                weather_info = (
                    f"Location: {data[0]['display_name'].split(',')[0]}, "
                    f"Today: {emoji} {desc}, "
                    f"Temp: {daily['temperature_2m_max'][0]}°C, "
                    f"Rain: {daily['precipitation_sum'][0]}mm, "
                    f"Wind: {current['windspeed']} km/h."
                )
    except Exception as e:
        print(f"Advisory weather fetch failed: {e}")
        weather_info = f"Weather: Could not fetch forecast for {location}. Advisories will be general."
    
    prompt = f"""
    You are Grama Vaani, a proactive Daily Farming Advisor.
    Your task is to provide a single, concise daily advisory message to the farmer based on their registered information and current weather.
    
    The farmer's language preference is **{lang_code}**. Respond *entirely* in this language.
    
    **Farmer's Context:**
    - Primary Crop: **{preferred_crop}**
    - Location: **{location}**
    - Current Weather Summary: **{weather_info}**
    
    **The Advisory must:**
    1.  Start with a friendly greeting and acknowledge the location/crop.
    2.  Provide 1-2 critical, action-oriented recommendations for the **{preferred_crop}** based on the weather (e.g., if rain is high, advise on drainage or pest watch; if hot, advise on irrigation timing).
    3.  End with a positive closing remark.
    4.  Use concise **Markdown (bolding and bullet points)** for clarity.
    5.  The entire response should be brief, a maximum of 4-5 sentences/points.
    """
    
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip()
        
        if location in ["India", "Not Set"]:
             text = translate_text(text, lang_code) if lang_code != "en" else text

        return text
    except Exception as e:
        print(f"Gemini advisory error: {e}")
        generic_advice = f"Hello! Remember to check your {preferred_crop} fields for any early signs of pests or disease. A morning walk through your farm can prevent big problems! Have a productive day."
        return translate_text(generic_advice, lang_code)


def get_gemini_response(question: str, language: str) -> str:
    if not chat_session:
        return "Gemini not ready."
    lang_code = language.split("-")[0]
    prompt = f"""
    You are Grama Vaani, an AI farming assistant.
    Answer in **{lang_code}** if possible.
    Question: "{question}"
    Be concise and helpful. Use **Markdown** for formatting (like **bold** or bullet points).
    If user asks for weather, reply: WEATHER_REQUEST: [city]
    """
    try:
        response = chat_session.send_message(prompt)
        text = response.text.strip()
        if text.startswith("WEATHER_REQUEST:"):
            city = text.split(":", 1)[1].strip()
            return get_weather(city, language)
        return text
    except Exception as e:
        print(f"Gemini error: {e}")
        return "Sorry, I encountered an error while processing your question."

def analyze_crop_image(image_bytes: bytes, language: str) -> str:
    if not vision_client or not gemini_model:
        return "Vision/Gemini not ready."
    try:
        image = vision.Image(content=image_bytes)
        labels = vision_client.label_detection(image=image)
        names = [l.description.lower() for l in labels.label_annotations[:10]]
        
        is_crop_related = any(word in l.description.lower() for l in labels.label_annotations for word in ["plant", "leaf", "crop", "soil", "vegetable", "fruit", "field"])
        
        if not is_crop_related:
            return "Not a clear crop image. Please upload a clear picture of the plant, leaf, or soil."
            
        lang_code = language.split("-")[0]
        
        prompt = f"""
        You are a crop pathologist.
        The image has been identified with these general labels: {', '.join(names)}.
        
        **Your task:** Based on the image content (assume the image is passed directly to the multimodal model):
        1.  Diagnose any visible pest, disease, or nutrient deficiency.
        2.  Provide a clear, brief remedy plan using **bullet points**.
        3.  Start with a salutation.
        
        Respond entirely in **{lang_code}**. Use Markdown for formatting.
        """
        
        image_part = Part.from_bytes(data=image_bytes, mime_type='image/jpeg') 
        
        response = gemini_model.generate_content(
            prompt, 
            contents=[image_part]
        )
        
        return response.text.strip()
    except Exception as e:
        print(f"Image analysis error: {e}")
        return "Analysis failed due to an error in the AI service connection."

def get_price_prediction(text: str, language: str) -> str:
    if not gemini_model:
        return "AI not ready."
    
    price_data = _get_fictional_price_data(text)
    
    lang_code = language.split("-")[0]
    prompt = f"""
    You are a professional market analyst for Grama Vaani.
    Your task is to provide a price report for a farmer.
    
    Respond in language: **{lang_code}**.
    
    Here is the raw data I found for the query "{text}":
    "{price_data}"

    If the data says 'No price data found', just apologize and ask them to be more specific.
    
    Otherwise, present this data in a professional report. The report must include:
    1.  A brief introductory sentence.
    2.  A **Markdown Table** with the columns: "Crop Variety", "Average Price (₹)", "Max Price (₹)", and "Min Price (₹)".
    3.  A one-sentence concluding remark or disclaimer (e.g., "Prices are fictional and for demonstration only.").
    """
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Price prediction error: {e}")
        return "Sorry, the price forecast service failed."

def _get_fictional_price_data(query: str) -> str:
    if "tomato" in query.lower() or "tamatar" in query.lower():
        return "Tomato (Nati): Avg: 50, Max: 65, Min: 40 | Tomato (Hybrid): Avg: 40, Max: 50, Min: 30"
    elif "onion" in query.lower() or "pyaj" in query.lower():
        return "Onion (Big): Avg: 80, Max: 100, Min: 70 | Onion (Small): Avg: 60, Max: 70, Min: 50"
    else:
        return "No price data found for that crop. Please specify a crop like 'tomato' or 'onion'."

def get_scheme_advice(text: str, language: str) -> str:
    if not gemini_model:
        return "AI not ready."

    scheme_list = _get_scheme_data_from_api(text)
    lang_code = language.split("-")[0]

    if not scheme_list:
        no_scheme_msg = "No specific government schemes were found for your query. Please try being more descriptive (e.g., 'subsidy for drip irrigation')."
        return translate_text(no_scheme_msg, lang_code) if lang_code != "en" else no_scheme_msg

    scheme_data_string = "\n".join([
        f"- Scheme: {s['title']}, Summary: {s['summary']}, Link: {s['link']}"
        for s in scheme_list
    ])

    prompt = f"""
    You are a government scheme advisor for Grama Vaani.
    Your task is to provide a helpful report for a farmer based on their query: "{text}".
    
    Respond in language: **{lang_code}**.

    I found the following matching schemes:
    {scheme_data_string}

    Please present these schemes in a professional report. The report must include:
    1.  An introductory sentence.
    2.  A **Markdown Table** with the columns: "Scheme Name", "Brief Summary", and "Link for Details".
    3.  A concluding remark encouraging the user to visit the links.
    """
    
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Scheme advice error: {e}")
        return "Sorry, the scheme advisor service failed."

def _get_scheme_data_from_api(text: str) -> List[dict]:
    params = {
        "api-key": GOVT_SCHEME_API_KEY,
        "format": "json",
        "limit": 3, 
        "filters[keywords]": text 
    }
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(GOVT_SCHEME_API_URL, params=params)
            response.raise_for_status() 
            data = response.json()

            if "records" in data and data["records"]:
                schemes = []
                for scheme in data["records"]:
                    summary = scheme.get("brief_description", "No Summary")
                    if len(summary) > 70:
                        summary = summary[:67] + "..."
                        
                    schemes.append({
                        "title": scheme.get("scheme_name", "No Title"),
                        "summary": summary,
                        "link": scheme.get("more_details_url_link", "#")
                    })
                return schemes
            else:
                return []
    except Exception as e:
        print(f"Scheme API error: {e}")
        return []

def text_to_speech_google(text: str, language_code: str) -> str:
    if not tts_client:
        raise HTTPException(500, "TTS not ready.")
    lang_map = {
        "en-US": ("en-US", "en-US-Standard-C"), 
        "hi-IN": ("hi-IN", "hi-IN-Wavenet-D"), 
        "ta-IN": ("ta-IN", "ta-IN-Wavenet-C"), 
        "te-IN": ("te-IN", "te-IN-Wavenet-D"), 
        "kn-IN": ("kn-IN", "kn-IN-Wavenet-A"), 
        "ml-IN": ("ml-IN", "ml-IN-Wavenet-B"), 
    }
    gc_lang, voice = lang_map.get(language_code, ("en-US", "en-US-Standard-C"))
    
    input_text = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(language_code=gc_lang, name=voice)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = tts_client.synthesize_speech(input=input_text, voice=voice_params, audio_config=audio_config)
    return base64.b64encode(response.audio_content).decode('utf-8')

def get_suggested_questions(history: List[Message], language: str) -> List[str]:
    if not gemini_model:
        return ["AI not ready for suggestions."]

    context_lines = [f"{msg.role.upper()}: {msg.text}" for msg in history]
    context = "\n".join(context_lines)
    lang_code = language.split("-")[0]
    
    prompt = f"""
    Based on the following conversation history, suggest **3 concise, single-sentence follow-up agricultural questions** that a farmer might want to ask next.
    
    The response **must** be a comma-separated list of exactly 3 questions.
    Example output (for English): "How much water is needed, What is the best fertilizer, When should I harvest"
    
    Conversation context (last message is the most important):
    ---
    {context}
    ---
    
    Generate the 3 questions in **{lang_code}**. Return only the comma-separated list.
    """
    
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip().replace('*', '').replace('\n', '')
        questions = [q.strip() for q in text.split(',') if q.strip()]
        
        default_questions = ["What is the current market price?", "How to prevent pest attacks?", "Where can I find government subsidies?"]
        
        while len(questions) < 3:
            if len(questions) < len(default_questions):
                 questions.append(default_questions[len(questions)])
            else:
                 questions.append("Tell me more about farming.") 
            
        return questions[:3]
        
    except Exception as e:
        print(f"Suggested questions generation error: {e}")
        return ["What is the current market price?", "How to prevent pest attacks?", "Where can I find government subsidies?"]

# --------------------------------------------------------------------------
# FASTAPI ENDPOINTS
# --------------------------------------------------------------------------

@app.post("/signup")
async def signup_endpoint(user_data: UserCreate, response: Response):
    return await perform_signup(user_data, response)

@app.post("/login")
async def login_endpoint(form_data: UserLogin, response: Response):
    return await perform_login(form_data, response)

@app.post("/logout")
async def logout_endpoint(response: Response):
    response.set_cookie(key="access_token", value="", httponly=True, max_age=-1, samesite="Lax", path="/")
    return {"message": "Logout successful"}

@app.put("/profile/update")
async def update_profile_endpoint(user_data: UserUpdateProfile, current_user: dict = Depends(get_current_user_dependency)):
    return await perform_update_profile(user_data, current_user)

@app.get("/", response_class=HTMLResponse)
async def read_login_page_endpoint(request: Request):
    token = request.cookies.get("access_token")
    if token:
        try:
            jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return Response(status_code=307, headers={"Location": "/dashboard"})
        except JWTError:
            pass
    return HTMLResponse(content=LOGIN_HTML_CONTENT) 

@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard_endpoint(current_user: dict = Depends(get_current_user_dependency)):
    user_name = current_user.get("name", "Farmer")
    user_email = current_user.get("email", "")
    user_phone = current_user.get("phone", "")
    user_location = current_user.get("location", "Not Set")
    user_crop = current_user.get("preferred_crop", "Paddy")
    user_initial = user_name[0].upper() if user_name else "U"
    
    content = HTML_CONTENT.replace("{{USER_NAME}}", user_name)
    content = content.replace("{{USER_EMAIL}}", user_email)
    content = content.replace("{{USER_INITIAL}}", user_initial)
    content = content.replace("{{USER_PHONE}}", user_phone)
    content = content.replace("{{USER_LOCATION}}", user_location)
    content = content.replace("{{USER_CROP}}", user_crop)
    
    return HTMLResponse(content=content)

@app.get("/chats", response_model=List[ChatSessionInfo])
async def get_chat_list_endpoint(current_user: dict = Depends(get_current_user_dependency)):
    user_email = current_user.get("email")
    chat_sessions = chats_collection.find(
        {"user_email": user_email},
        {"_id": 1, "title": 1, "created_at": 1}
    ).sort("created_at", pymongo.DESCENDING)
    
    return [ChatSessionInfo(id=str(chat["_id"]), title=chat["title"]) for chat in chat_sessions]

@app.get("/chats/{chat_id}", response_model=ChatSessionDetail)
async def get_chat_details_endpoint(chat_id: str, current_user: dict = Depends(get_current_user_dependency)):
    user_email = current_user.get("email")
    
    try:
        chat = chats_collection.find_one({"_id": ObjectId(chat_id), "user_email": user_email})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chat ID format")
        
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found or access denied")
        
    return ChatSessionDetail(
        id=str(chat["_id"]), title=chat["title"],
        messages=[Message(**msg) for msg in chat["messages"]]
    )

@app.post("/save_chat")
async def save_chat_endpoint(request: ChatSaveRequest, current_user: dict = Depends(get_current_user_dependency)):
    user_email = current_user.get("email")
    chat_data = {
        "user_email": user_email,
        "messages": [msg.model_dump() for msg in request.messages],
        "updated_at": datetime.utcnow()
    }

    if request.chat_id:
        try:
            chat_id = ObjectId(request.chat_id)
        except Exception:
             raise HTTPException(status_code=400, detail="Invalid chat ID format")
             
        chats_collection.update_one(
            {"_id": chat_id, "user_email": user_email}, 
            {"$set": {"messages": chat_data["messages"], "updated_at": chat_data["updated_at"]}}
        )
        chat = chats_collection.find_one({"_id": chat_id}, {"title": 1})
        title = chat.get("title", "Chat")
    else:
        title = "New Chat"
        if request.messages and request.messages[0].role == 'user':
            title = request.messages[0].text[:30].strip()
            if len(request.messages[0].text) > 30:
                title += "..."

        chat_data["title"] = title
        chat_data["created_at"] = datetime.utcnow()
        
        result = chats_collection.insert_one(chat_data)
        chat_id = result.inserted_id

    return {"chat_id": str(chat_id), "title": title}

@app.get("/advisory", response_model=AdvisoryResponse)
async def advisory_handler_endpoint(language: str = Query("en-US"), current_user: dict = Depends(get_current_user_dependency)):
    return await handle_advisory(language, current_user)

@app.post("/chat")
async def chat_handler_endpoint(request: ChatRequest, current_user: dict = Depends(get_current_user_dependency)):
    try:
        text = get_gemini_response(request.text, request.language)
        clean_speech_text = clean_text_for_speech(text)
        audio = text_to_speech_google(clean_speech_text, request.language)
        
        return {"text": text, "audio": audio}
    except Exception as e:
        print(f"Chat error: {e}")
        err = "Sorry, something went wrong with the AI service."
        try:
            audio = text_to_speech_google(clean_text_for_speech(err), request.language)
        except:
             audio = None
        return {"text": err, "audio": audio}

@app.post("/suggest_questions")
async def suggested_questions_handler_endpoint(request: SuggestedQuestionsRequest, current_user: dict = Depends(get_current_user_dependency)):
    try:
        questions = get_suggested_questions(request.history, request.language)
        return {"questions": questions}
    except Exception as e:
        print(f"API Suggested questions error: {e}")
        return {"questions": ["What is the current market price?", "How to prevent pest attacks?", "Where can I find government subsidies?"]}

@app.post("/analyse-crop")
async def analyse_crop_handler_endpoint(file: UploadFile = File(...), language: str = Form("en-US"), current_user: dict = Depends(get_current_user_dependency)):
    try:
        content = await file.read()
        text = analyze_crop_image(content, language)
        clean_speech_text = clean_text_for_speech(text)
        audio = text_to_speech_google(clean_speech_text, language) 
        
        return {"text": text, "audio": audio}
    except Exception as e:
        print(f"Crop error: {e}")
        err = "Image analysis failed due to a server error."
        try:
            audio = text_to_speech_google(clean_text_for_speech(err), language)
        except:
             audio = None
        raise HTTPException(500, detail={"text": err, "audio": audio})

@app.get("/weather/{city}")
async def weather_handler_endpoint(city: str, language: str = Query("en-US"), current_user: dict = Depends(get_current_user_dependency)):
    try:
        text = get_weather(city, language)
        clean_speech_text = clean_text_for_speech(text)
        audio = text_to_speech_google(clean_speech_text, language)
        return {"text": text, "audio": audio}
    except Exception as e:
        print(f"Weather error: {e}")
        err = "Could not fetch weather."
        audio = text_to_speech_google(clean_text_for_speech(err), language)
        return {"text": err, "audio": audio}

@app.post("/price")
async def price_handler_endpoint(request: ChatRequest, current_user: dict = Depends(get_current_user_dependency)):
    try:
        text = get_price_prediction(request.text, request.language)
        return {"text": text, "audio": None}
    except Exception as e:
        print(f"Price error: {e}")
        err = "Price forecast failed."
        return {"text": err, "audio": None}

@app.post("/scheme")
async def scheme_handler_endpoint(request: ChatRequest, current_user: dict = Depends(get_current_user_dependency)):
    try:
        text = get_scheme_advice(request.text, request.language)
        return {"text": text, "audio": None}
    except Exception as e:
        print(f"Scheme error: {e}")
        err = "Scheme info failed."
        return {"text": err, "audio": None}

@app.get("/auth/google")
async def auth_google_endpoint():
    raise HTTPException(501, "Google Auth not implemented. Requires OAuth2 setup.")

@app.get("/auth/google/callback")
async def auth_google_callback_endpoint():
    raise HTTPException(501, "Google Auth not implemented. Requires OAuth2 setup.")


if __name__ == "__main__":
    print("--- Starting Grama Vaani (FULL MONOLITHIC CODE) ---")
    print("Open: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)