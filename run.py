#!/usr/bin/env python3
"""
LangLearn Studio - ishga tushirish skripti
Ishlatish: python run.py
"""
import os, sys, subprocess, time, webbrowser, threading

def check_deps():
    try:
        import flask, flask_sqlalchemy
    except ImportError:
        print("📦 Kerakli kutubxonalar o'rnatilmoqda...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                               'flask', 'flask-sqlalchemy', '--break-system-packages', '-q'])

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    check_deps()
    # change to script dir
    base = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base)
    os.makedirs(os.path.join(base, 'data'), exist_ok=True)
    os.makedirs(os.path.join(base, 'static', 'audio'), exist_ok=True)
    os.makedirs(os.path.join(base, 'static', 'img'), exist_ok=True)
    os.makedirs(os.path.join(base, 'templates'), exist_ok=True)
    # index.html ni templates/ ga ko'chirish (agar kerak bo'lsa)
    src_html = os.path.join(base, 'index.html')
    dst_html = os.path.join(base, 'templates', 'index.html')
    if os.path.exists(src_html) and not os.path.exists(dst_html):
        import shutil
        shutil.copy2(src_html, dst_html)

    print("""
╔══════════════════════════════════════════╗
║        🌟 LangLearn Studio               ║
║   Til o'rgatish platformasi              ║
╠══════════════════════════════════════════╣
║  URL: http://127.0.0.1:5000              ║
║  To'xtatish: Ctrl+C                      ║
╚══════════════════════════════════════════╝
""")
    threading.Thread(target=open_browser, daemon=True).start()
    from app import app, init_db
    init_db()
    app.run(debug=False, port=5000, host='0.0.0.0')
