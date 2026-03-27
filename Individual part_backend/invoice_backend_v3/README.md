# Receipt and Invoice Digitizer

A Flask-based web application for digitizing and managing receipts and invoices.

## Features

- User authentication (Register, Login, Forgot Password)
- Upload receipts and invoices (images and PDFs)
- View and manage uploaded documents
- Search and filter receipts by vendor
- Delete receipts
- Session-based authentication

## Project Structure

```
receipt-invoice-digitizer/
├── app.py                  # Main Flask application
├── requirements.txt        # Python dependencies
├── README.md              # This file
├── users.db               # SQLite database (created automatically)
├── templates/             # HTML templates
│   ├── login_page.html
│   ├── register.html
│   ├── forgotpassword.html
│   └── home.html          # Dashboard
├── uploads/               # Uploaded receipts storage
└── static/                # Static files (CSS, JS, images)
```

## Setup Instructions

1. **Install Python Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Application**
   ```bash
   python app.py
   ```

3. **Access the Application**
   - Open your browser and go to: `http://localhost:5000`
   - Register a new account
   - Login and start uploading receipts!

## Usage

1. **Register**: Create a new account with username, email, password, and phone
2. **Login**: Use your username/email and password to login
3. **Upload Receipts**: Drag & drop or click to select receipt images/PDFs
4. **Manage**: View, search, and delete your receipts
5. **Logout**: Click the logout button in the navbar

## Default Configuration

- **Server Port**: 5000
- **Debug Mode**: Enabled (disable in production)
- **Max Upload Size**: 16MB
- **Allowed File Types**: PNG, JPG, JPEG, GIF, PDF

## Database Schema

### Users Table
- id (PRIMARY KEY)
- username (UNIQUE)
- email (UNIQUE)
- password (hashed with bcrypt)
- phone

### Receipts Table
- receipt_id (PRIMARY KEY)
- user_id (FOREIGN KEY)
- filename
- upload_date
- vendor_name
- invoice_number
- date
- total_amount
- tax

## Security Features

- Password hashing with bcrypt
- Session-based authentication
- Secure file upload with filename sanitization
- File type validation

## Future Enhancements

- OCR integration for automatic data extraction
- Export to Excel/CSV
- Analytics dashboard
- Email integration for password reset
- Multi-language support

## Notes

- The database is created automatically when you first run the application
- Uploaded files are stored in the `uploads/` directory
- Make sure to disable debug mode in production environments
